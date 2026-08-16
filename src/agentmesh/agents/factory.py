from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.adk_spark.agent import GoogleADKAgent
from agentmesh.agents.base import BaseAgent
from agentmesh.agents.langgraph_copilot.agent import ConversationAgent
from agentmesh.config import Settings
from agentmesh.core.exceptions import ValidationError
from agentmesh.integrations.groq.client import GroqStructuredOutputClient


def create_langgraph_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the LangGraph worker with the configured model provider."""

    if settings.llm_provider.strip().lower() == "mock":
        return ConversationAgent(auto_register=False), lambda: None
    client = _create_groq_client(settings)
    return ConversationAgent(auto_register=False, llm_client=client), client.close


def create_google_adk_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the Google ADK worker using Groq through ADK's LiteLLM connector."""

    if settings.llm_provider.strip().lower() == "mock":
        return GoogleADKAgent(auto_register=False), lambda: None
    api_key = _groq_api_key(settings)
    return (
        GoogleADKAgent(
            auto_register=False,
            model_name=settings.groq_model,
            api_key=api_key,
        ),
        lambda: None,
    )


def _create_groq_client(settings: Settings) -> GroqStructuredOutputClient:
    if settings.llm_provider.strip().lower() != "groq":
        raise ValidationError("Worker LLM_PROVIDER must be mock or groq.")
    return GroqStructuredOutputClient(
        api_key=_groq_api_key(settings),
        model=settings.groq_model,
        api_base=settings.groq_api_base,
        reasoning_effort=settings.groq_reasoning_effort,
        temperature=settings.groq_temperature,
        max_completion_tokens=settings.groq_max_completion_tokens,
        timeout_seconds=settings.groq_timeout_seconds,
    )


def _groq_api_key(settings: Settings) -> str:
    if settings.llm_provider.strip().lower() != "groq":
        raise ValidationError("Google ADK currently requires LLM_PROVIDER=groq in AgentMesh.")
    api_key = (
        settings.groq_api_key.get_secret_value().strip()
        if settings.groq_api_key is not None
        else ""
    )
    if not api_key:
        raise ValidationError("GROQ_API_KEY is required when LLM_PROVIDER=groq.")
    return api_key
