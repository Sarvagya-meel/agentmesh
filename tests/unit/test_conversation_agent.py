import os

from langchain_core.messages import HumanMessage
from langgraph.graph.message import add_messages

from agentmesh.agents.agent_langgraph_copilot.agent import ConversationAgent
from agentmesh.config import Settings
from agentmesh.core.observability import configure_langsmith


class FakeTextCompletionClient:
    model = "fake-platform-model"

    def create_text_completion(self, *, messages: list[dict[str, str]]) -> str:
        return f"Generated for: {messages[-1]['content']}"


class RecordingTextCompletionClient:
    model = "recording-model"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def create_text_completion(self, *, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return f"Turn {len(self.calls)} response"


def test_conversation_agent_builds_a_graph_and_returns_a_reply() -> None:
    agent = ConversationAgent()

    assert "generate_response" in agent.graph.nodes
    assert "human_approval" in agent.graph.nodes

    result = agent.run_task({"messages": ["Plan a launch for my product."]})
    assert "draft_reply" in result
    assert "final_reply" in result
    assert "messages" not in result


def test_conversation_agent_can_resume_after_human_input() -> None:
    agent = ConversationAgent(auto_register=False)

    started = agent.start_conversation(
        "Plan a launch for my product.",
        thread_id="test-human-input",
    )
    assert started["status"] == "AWAITING_APPROVAL"
    assert started["interrupt"]["options"] == ["approve", "revise", "reject"]

    resumed = agent.resume_conversation("test-human-input", "approve")
    assert resumed["status"] == "COMPLETED"
    assert resumed["approved"] is True
    assert resumed["final_reply"] == started["draft_reply"]


def test_conversation_agent_revises_the_same_checkpoint_with_feedback() -> None:
    agent = ConversationAgent(auto_register=False)
    started = agent.start_conversation("Draft a launch plan.", thread_id="revision-thread")

    revised = agent.resume_conversation(
        "revision-thread",
        "revise",
        "Add a security review.",
    )

    assert revised["status"] == "AWAITING_APPROVAL"
    assert revised["thread_id"] == started["thread_id"]
    assert "security review" in revised["draft_reply"].lower()


def test_conversation_agent_rejects_with_an_explicit_terminal_result() -> None:
    agent = ConversationAgent(auto_register=False)
    started = agent.start_conversation("Draft a launch plan.", thread_id="reject-thread")

    rejected = agent.resume_conversation(started["thread_id"], "reject")

    assert rejected["status"] == "REJECTED"
    assert rejected["rejected"] is True
    assert rejected["final_reply"] == "Approval rejected."


def test_conversation_agent_advertises_work_capabilities_and_runtime_features() -> None:
    card = ConversationAgent(auto_register=False).agent_card()

    assert card.capabilities == ["CHAT", "DRAFT", "REVIEW"]
    assert card.metadata["framework"] == "langgraph"
    assert card.metadata["approval_modes"] == ["output_review"]


def test_conversation_agent_accepts_the_platform_text_completion_contract() -> None:
    agent = ConversationAgent(
        auto_register=False,
        llm_client=FakeTextCompletionClient(),
    )

    result = agent.run_conversation("Explain dependency inversion.")

    assert result["status"] == "COMPLETED"
    assert result["llm_model"] == "fake-platform-model"
    assert "Explain dependency inversion." in result["final_reply"]


def test_conversation_agent_includes_validated_dependency_outputs_in_prompt() -> None:
    prompt = ConversationAgent._task_prompt(
        {
            "description": "Review the earlier result.",
            "payload": {
                "goal": "Produce a final answer.",
                "workflow_context": {
                    "resolved_inputs": {
                        "step_0": {"final_reply": "Dependency result"}
                    }
                },
            },
        }
    )

    assert "Validated dependency outputs:" in prompt
    assert '"final_reply": "Dependency result"' in prompt
    assert "Use these dependency outputs as input" in prompt


def test_add_messages_updates_an_existing_message_by_id() -> None:
    original = HumanMessage(id="message-1", content="Original")
    corrected = HumanMessage(id="message-1", content="Corrected")

    merged = add_messages([original], [corrected])

    assert len(merged) == 1
    assert merged[0].content == "Corrected"


def test_conversation_agent_retains_multi_turn_history_by_thread() -> None:
    client = RecordingTextCompletionClient()
    agent = ConversationAgent(
        auto_register=False,
        llm_client=client,
        max_evaluation_attempts=1,
    )

    agent.start_conversation(
        "My preferred destination is Dubai.",
        thread_id="multi-turn-thread",
        approval_required=False,
    )
    second = agent.start_conversation(
        "Which destination did I prefer?",
        thread_id="multi-turn-thread",
        approval_required=False,
    )

    assert second["status"] == "COMPLETED"
    assert [message["role"] for message in client.calls[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert client.calls[1][1]["content"] == "My preferred destination is Dubai."
    assert client.calls[1][2]["content"] == "Turn 1 response"
    snapshot = agent.graph.get_state(agent._config("multi-turn-thread"))
    assert len(snapshot.values["messages"]) == 4


async def test_async_task_contract_matches_sync_result_shape() -> None:
    sync_agent = ConversationAgent(auto_register=False)
    async_agent = ConversationAgent(auto_register=False)
    payload = {
        "messages": ["Explain durable execution."],
        "thread_id": "async-contract",
        "approval_required": False,
    }

    sync_result = sync_agent.run_task(payload)
    async_result = await async_agent.arun_task(payload)

    assert async_result["status"] == sync_result["status"] == "COMPLETED"
    assert async_result["final_reply"] == sync_result["final_reply"]


def test_evaluator_optimizer_loop_is_bounded() -> None:
    client = RecordingTextCompletionClient()
    agent = ConversationAgent(
        auto_register=False,
        llm_client=client,
        max_evaluation_attempts=3,
    )

    result = agent.start_conversation(
        "Answer briefly.",
        thread_id="bounded-evaluator",
        approval_required=False,
    )

    assert result["status"] == "COMPLETED"
    assert result["evaluation_attempts"] == 3
    assert result["quality_score"] == 0.5
    assert len(client.calls) == 3
    snapshot = agent.graph.get_state(agent._config("bounded-evaluator"))
    assert len(snapshot.values["messages"]) == 2


async def test_long_term_memory_is_opt_in_namespaced_and_deletable() -> None:
    agent = ConversationAgent(
        auto_register=False,
        long_term_memory_enabled=True,
    )
    await agent.arun_task(
        {
            "messages": ["Remember my preference."],
            "thread_id": "alice-one",
            "user_id": "alice",
            "memory_opt_in": True,
            "memory_updates": {"destination": "Dubai"},
            "approval_required": False,
        }
    )
    await agent.arun_task(
        {
            "messages": ["Load my preference."],
            "thread_id": "alice-two",
            "user_id": "alice",
            "memory_opt_in": True,
            "approval_required": False,
        }
    )
    await agent.arun_task(
        {
            "messages": ["Load my preference."],
            "thread_id": "bob-one",
            "user_id": "bob",
            "memory_opt_in": True,
            "approval_required": False,
        }
    )

    alice = await agent.graph.aget_state(agent._config("alice-two"))
    bob = await agent.graph.aget_state(agent._config("bob-one"))
    assert alice.values["long_term_memories"][0]["value"] == "Dubai"
    assert bob.values["long_term_memories"] == []

    await agent.arun_task(
        {
            "messages": ["Forget my preference."],
            "thread_id": "alice-three",
            "user_id": "alice",
            "memory_opt_in": True,
            "memory_delete_keys": ["destination"],
            "approval_required": False,
        }
    )
    deleted = await agent.graph.aget_state(agent._config("alice-three"))
    assert deleted.values["long_term_memories"] == []


async def test_checkpoint_history_forks_without_changing_source_thread() -> None:
    agent = ConversationAgent(auto_register=False)
    await agent.arun_task(
        {
            "messages": ["Create a checkpoint."],
            "thread_id": "source-thread",
            "approval_required": False,
        }
    )
    history = await agent.checkpoint_history("source-thread")
    source_before = await agent.graph.aget_state(agent._config("source-thread"))

    fork = await agent.fork_checkpoint(
        "source-thread",
        str(history[0]["checkpoint_id"]),
        new_thread_id="fork-thread",
        state_updates={"draft_reply": "Forked draft"},
    )
    source_after = await agent.graph.aget_state(agent._config("source-thread"))

    assert fork["thread_id"] == "fork-thread"
    assert source_after.config == source_before.config
    assert source_after.values["draft_reply"] == source_before.values["draft_reply"]


def test_mermaid_export_contains_every_copilot_node() -> None:
    agent = ConversationAgent(auto_register=False)
    mermaid = agent.graph_mermaid()

    for node in agent.graph.nodes:
        assert node in mermaid


def test_langsmith_is_disabled_by_default() -> None:
    previous_langsmith = os.environ.get("LANGSMITH_TRACING")
    previous_langchain = os.environ.get("LANGCHAIN_TRACING_V2")
    try:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        configure_langsmith(Settings(langsmith_tracing=False))
        assert os.environ["LANGSMITH_TRACING"] == "false"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    finally:
        if previous_langsmith is None:
            os.environ.pop("LANGSMITH_TRACING", None)
        else:
            os.environ["LANGSMITH_TRACING"] = previous_langsmith
        if previous_langchain is None:
            os.environ.pop("LANGCHAIN_TRACING_V2", None)
        else:
            os.environ["LANGCHAIN_TRACING_V2"] = previous_langchain


def test_langsmith_env_file_values_are_exported_for_sdk() -> None:
    previous = {
        key: os.environ.get(key)
        for key in (
            "LANGSMITH_TRACING",
            "LANGCHAIN_TRACING_V2",
            "LANGSMITH_PROJECT",
            "LANGCHAIN_PROJECT",
            "LANGSMITH_ENDPOINT",
            "LANGCHAIN_ENDPOINT",
            "LANGSMITH_API_KEY",
            "LANGCHAIN_API_KEY",
        )
    }
    try:
        configure_langsmith(
            Settings(
                langsmith_tracing=True,
                langsmith_project="test-project",
                langsmith_endpoint="https://example.test",
                langsmith_api_key="test-key",
            )
        )

        assert os.environ["LANGSMITH_TRACING"] == "true"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGSMITH_PROJECT"] == "test-project"
        assert os.environ["LANGCHAIN_PROJECT"] == "test-project"
        assert os.environ["LANGSMITH_ENDPOINT"] == "https://example.test"
        assert os.environ["LANGCHAIN_ENDPOINT"] == "https://example.test"
        assert os.environ["LANGSMITH_API_KEY"] == "test-key"
        assert os.environ["LANGCHAIN_API_KEY"] == "test-key"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
