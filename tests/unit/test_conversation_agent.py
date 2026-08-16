from agentmesh.agents.langgraph_copilot.agent import ConversationAgent


def test_conversation_agent_builds_a_graph_and_returns_a_reply() -> None:
    agent = ConversationAgent()

    assert "draft_response" in agent.graph.nodes
    assert "human_approval" in agent.graph.nodes

    result = agent.run_task({"messages": ["Plan a launch for my product."]})
    assert "draft_reply" in result
    assert "final_reply" in result


def test_conversation_agent_can_resume_after_human_input() -> None:
    agent = ConversationAgent(auto_register=False)

    started = agent.start_conversation(
        "Plan a launch for my product.",
        thread_id="test-human-input",
    )
    assert started["status"] == "awaiting_human"
    assert started["interrupt"]["options"] == ["approve", "reject"]

    resumed = agent.resume_conversation("test-human-input", "approve")
    assert resumed["status"] == "completed"
    assert resumed["approved"] is True
    assert resumed["final_reply"] == started["draft_reply"]
