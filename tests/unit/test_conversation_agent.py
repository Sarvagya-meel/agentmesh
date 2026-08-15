from agentmesh.agents.conversation_agent.agent import ConversationAgent


def test_conversation_agent_builds_a_graph_and_returns_a_reply() -> None:
    agent = ConversationAgent()

    assert "draft_response" in agent.graph.nodes
    assert "human_approval" in agent.graph.nodes

    result = agent.run_task({"messages": ["Plan a launch for my product."]})
    assert "draft_reply" in result
    assert "final_reply" in result
