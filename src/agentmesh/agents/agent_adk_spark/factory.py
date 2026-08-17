from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.agent_adk_spark.agent import GoogleADKAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.providers import groq_api_key


def create_google_adk_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the Google ADK worker with its configured model connector."""

    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return GoogleADKAgent(auto_register=False), lambda: None

    try:
        api_key = groq_api_key(settings)
    except ValidationError:
        return GoogleADKAgent(auto_register=False), lambda: None

    return (
        GoogleADKAgent(
            auto_register=False,
            model_name=settings.groq_model,
            api_key=api_key,
        ),
        lambda: None,
    )
