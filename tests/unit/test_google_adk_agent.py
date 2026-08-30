from google.adk.sessions import DatabaseSessionService

from agentmesh.agents.agent_adk_spark.agent import GoogleADKAgent
from agentmesh.agents.agent_adk_spark.factory import create_google_adk_worker_agent
from agentmesh.config import Settings


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


def test_google_adk_factory_falls_back_to_mock_when_key_missing() -> None:
    settings = Settings(llm_provider="groq", groq_api_key=None)
    agent, _ = create_google_adk_worker_agent(settings)

    result = agent.run_task({"messages": ["Summarize the release checklist."]})

    assert result["status"] == "success"
    assert result["source"] == "local_fallback"


def test_google_adk_factory_falls_back_for_gpt_oss_tool_choice_mismatch() -> None:
    settings = Settings(llm_provider="groq", groq_api_key="test-key")
    agent, _ = create_google_adk_worker_agent(settings)

    result = agent.run_task({"messages": ["Is the sky blue on a clear day?"]})

    assert result["status"] == "success"
    assert result["source"] == "local_fallback"
    assert result["model"] == "openai/gpt-oss-120b"


def test_google_adk_agent_uses_stable_workflow_task_session_identity() -> None:
    agent = GoogleADKAgent(auto_register=False)

    result = agent.run_task(
        {
            "workflow_id": "workflow-123",
            "task_id": "task-456",
            "conversation_id": "conversation-789",
            "messages": ["Continue this task."],
        }
    )

    assert result["session_id"] == "agent:workflow-123:task-456"


async def test_google_adk_agent_closes_database_sessions_from_async_runtime() -> None:
    session_service = DatabaseSessionService(db_url="sqlite+aiosqlite:///:memory:")
    agent = GoogleADKAgent(
        auto_register=False,
        model_name="test-model",
        api_key="test-key",
        session_service=session_service,
    )
    event_thread = agent._event_thread

    agent.close()

    assert event_thread is not None
    assert not event_thread.is_alive()
