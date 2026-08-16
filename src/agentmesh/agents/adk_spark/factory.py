from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.adk_spark.agent import GoogleADKAgent
from agentmesh.agents.common.agent_models import BaseAgent
from agentmesh.agents.common.providers import groq_api_key
from agentmesh.config import Settings


def create_google_adk_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the Google ADK worker with its configured model connector."""

    if settings.llm_provider.strip().lower() == "mock":
        return GoogleADKAgent(auto_register=False), lambda: None
    return (
        GoogleADKAgent(
            auto_register=False,
            model_name=settings.groq_model,
            api_key=groq_api_key(settings),
        ),
        lambda: None,
    )
