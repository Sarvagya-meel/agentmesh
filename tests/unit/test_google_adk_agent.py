from agentmesh.agents.adk_spark.agent import GoogleADKAgent


def test_google_adk_agent_returns_structured_response() -> None:
    agent = GoogleADKAgent(auto_register=False)
    result = agent.run_task({"messages": ["Design a launch plan for my product."]})

    assert result["status"] == "success"
    assert result["agent"] == "googleADK-Chatagent"
    assert "final_reply" in result
    assert result["source"] == "local_fallback"


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
