from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.agent_adk_spark.agent import GoogleADKAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.core.config import Settings
from agentmesh.core.frameworks.google_adk import create_google_adk_session_service
from agentmesh.core.models.exceptions import ValidationError


def create_google_adk_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the Google ADK worker with its configured model connector."""

    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return (
            GoogleADKAgent(
                auto_register=False,
                model_name="mock",
                executor=lambda prompt: f"Mock Google ADK response: {prompt}",
            ),
            lambda: None,
        )

    if provider != "litellm":
        raise ValidationError("LLM_PROVIDER must be mock or litellm for Google ADK.")
    api_key = settings.litellm_master_key.get_secret_value().strip()
    if not api_key:
        raise ValidationError("LITELLM_MASTER_KEY is required when LLM_PROVIDER=litellm.")
    model_name = settings.litellm_model.strip()
    if not model_name:
        raise ValidationError("LITELLM_MODEL is required when LLM_PROVIDER=litellm.")

    session_service = create_google_adk_session_service(settings)
    agent = GoogleADKAgent(
        auto_register=False,
        model_name=model_name,
        max_completion_tokens=settings.google_adk_max_completion_tokens,
        api_key=api_key,
        api_base=settings.litellm_api_base,
        session_service=session_service,
    )
    return agent, agent.close
