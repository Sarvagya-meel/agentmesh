import pytest
from google.adk.sessions import DatabaseSessionService

from agentmesh.agents.agent_adk_spark.agent import GoogleADKAgent
from agentmesh.agents.agent_adk_spark.factory import create_google_adk_worker_agent
from agentmesh.core.config import Settings
from agentmesh.core.models.exceptions import ModelProviderError, ValidationError


def test_google_adk_agent_rejects_unconfigured_model_runtime() -> None:
    agent = GoogleADKAgent(auto_register=False)

    with pytest.raises(ModelProviderError, match="no configured model runtime"):
        agent.run_task({"messages": ["Design a launch plan for my product."]})


def test_google_adk_agent_uses_injected_llm_executor() -> None:
    agent = GoogleADKAgent(
        auto_register=False,
        model_name="test-model",
        executor=lambda prompt: f"LLM answer for: {prompt}",
    )

    result = agent.run_task({"messages": ["Explain event sourcing."]})

    assert result["source"] == "google_adk_llm"
    assert result["model"] == "test-model"
    assert result["final_reply"] == "LLM answer for: Explain event sourcing."


def test_google_adk_factory_rejects_missing_gateway_key() -> None:
    settings = Settings(llm_provider="litellm", litellm_master_key="")

    with pytest.raises(ValidationError, match="LITELLM_MASTER_KEY"):
        create_google_adk_worker_agent(settings)


def test_google_adk_factory_mock_agent_can_execute() -> None:
    agent, close = create_google_adk_worker_agent(Settings(llm_provider="mock"))

    result = agent.run_task({"messages": ["Say ready."]})

    assert result["status"] == "success"
    assert result["model"] == "mock"
    assert result["final_reply"] == "Mock Google ADK response: Say ready."
    close()


def test_google_adk_factory_rejects_missing_litellm_model() -> None:
    settings = Settings(
        llm_provider="litellm",
        litellm_master_key="test-key",
        litellm_model="",
    )

    with pytest.raises(ValidationError, match="LITELLM_MODEL"):
        create_google_adk_worker_agent(settings)


def test_google_adk_factory_uses_litellm_gateway_alias() -> None:
    settings = Settings(
        llm_provider="litellm",
        litellm_master_key="test-key",
        litellm_api_base="http://litellm:4000/v1",
        litellm_model="agentmesh-groq",
        google_adk_max_completion_tokens=384,
        google_adk_session_backend="memory",
    )
    agent, close = create_google_adk_worker_agent(settings)

    assert isinstance(agent, GoogleADKAgent)
    assert agent.model_name == "agentmesh-groq"
    assert agent._adk_runner is not None
    assert agent._adk_runner.agent.model.model == "openai/agentmesh-groq"
    assert agent._adk_runner.agent.model._additional_args == {
        "drop_params": True,
        "include_reasoning": False,
        "max_tokens": 384,
        "api_key": "test-key",
        "api_base": "http://litellm:4000/v1",
    }

    close()


def test_google_adk_agent_uses_stable_workflow_task_session_identity() -> None:
    agent = GoogleADKAgent(auto_register=False, executor=lambda prompt: prompt)

    result = agent.run_task(
        {
            "workflow_id": "workflow-123",
            "task_id": "task-456",
            "conversation_id": "conversation-789",
            "messages": ["Continue this task."],
        }
    )

    assert result["session_id"] == "agent:workflow-123:task-456"


def test_google_adk_agent_includes_validated_dependency_outputs_in_prompt() -> None:
    prompt = GoogleADKAgent._task_prompt(
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


async def test_google_adk_agent_closes_database_sessions_from_async_runtime() -> None:
    session_service = DatabaseSessionService(db_url="sqlite+aiosqlite:///:memory:")
    agent = GoogleADKAgent(
        auto_register=False,
        model_name="test-model",
        api_key="test-key",
        api_base="http://litellm:4000/v1",
        session_service=session_service,
    )
    event_thread = agent._event_thread

    agent.close()

    assert event_thread is not None
    assert not event_thread.is_alive()


def test_google_adk_runner_can_attach_litellm_request_metadata() -> None:
    session_service = DatabaseSessionService(db_url="sqlite+aiosqlite:///:memory:")

    runner = GoogleADKAgent._build_adk_runner(
        "test-key",
        "http://litellm:4000/v1",
        "agentmesh-groq",
        384,
        session_service,
        request_metadata={
            "agent_id": "googleADK-Chatagent",
            "framework": "google_adk",
            "model_alias": "agentmesh-groq",
            "session_id": "agent:workflow-123:task-456",
            "user_id": "streamlit-user",
        },
    )

    assert runner.agent.model._additional_args["metadata"] == {
        "agent_id": "googleADK-Chatagent",
        "framework": "google_adk",
        "model_alias": "agentmesh-groq",
        "session_id": "agent:workflow-123:task-456",
        "user_id": "streamlit-user",
    }
    assert runner.agent.model._additional_args["user"] == "streamlit-user"


def test_google_adk_provider_failures_are_domain_errors() -> None:
    agent = GoogleADKAgent(
        auto_register=False,
        model_name="test-model",
        api_key="test-key",
        api_base="http://litellm:4000/v1",
        session_service=DatabaseSessionService(db_url="sqlite+aiosqlite:///:memory:"),
    )

    async def fail_provider(*args, **kwargs):
        raise RuntimeError("rate limit")

    agent._execute_adk = fail_provider

    with pytest.raises(ModelProviderError, match="provider request failed"):
        agent.run_task({"messages": ["Say hello."]})

    agent.close()
