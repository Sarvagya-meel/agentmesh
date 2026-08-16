from agentmesh.agents.adk_spark.agent import GoogleADKAgent


def test_google_adk_agent_returns_structured_response() -> None:
    agent = GoogleADKAgent(auto_register=False)
    result = agent.run_task({"messages": ["Design a launch plan for my product."]})

    assert result["status"] == "success"
    assert result["agent"] == "adk-spark"
    assert "final_reply" in result
    assert "google_adk_adapter" in result["source"]
