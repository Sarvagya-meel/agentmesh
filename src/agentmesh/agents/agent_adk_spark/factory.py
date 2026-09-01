from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.agent_adk_spark.agent import GoogleADKAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.config import Settings
from agentmesh.core.frameworks.google_adk import create_google_adk_session_service
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
    model_name = settings.google_adk_model.strip() or settings.groq_model
    if _uses_adk_incompatible_groq_model(model_name):
        return GoogleADKAgent(auto_register=False, model_name=model_name), lambda: None

    session_service = create_google_adk_session_service(settings)
    agent = GoogleADKAgent(
        auto_register=False,
        model_name=model_name,
        api_key=api_key,
        session_service=session_service,
    )
    return agent, agent.close


def _uses_adk_incompatible_groq_model(model_name: str) -> bool:
    """Return true for Groq models that currently emit unsupported ADK tool calls."""

    normalized = model_name.strip().lower()
    return normalized.startswith("openai/gpt-oss")
