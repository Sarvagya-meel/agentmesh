from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.agent_langgraph_orchestrator_supervisor.planner import (
    CapabilityWorkflowPlanner,
    GroqWorkflowPlanner,
    WorkflowPlanner,
)
from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.providers.groq import GroqStructuredOutputClient


def create_workflow_planner(
    settings: Settings,
) -> tuple[WorkflowPlanner, Callable[[], None]]:
    """Create the configured planning brain and its cleanup callback."""

    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return CapabilityWorkflowPlanner(), lambda: None
    if provider != "groq":
        raise ValidationError("LLM_PROVIDER must be mock or groq for orchestration.")

    api_key = (
        settings.litellm_master_key.get_secret_value().strip()
        if settings.litellm_enabled
        else (
            settings.groq_api_key.get_secret_value().strip()
            if settings.groq_api_key is not None
            else ""
        )
    )
    if not api_key:
        raise ValidationError(
            "GROQ_API_KEY or the configured LiteLLM gateway key is required "
            "when LLM_PROVIDER=groq."
        )

    client = GroqStructuredOutputClient(
        api_key=api_key,
        model=settings.litellm_model if settings.litellm_enabled else settings.groq_model,
        api_base=settings.litellm_api_base if settings.litellm_enabled else settings.groq_api_base,
        reasoning_effort=settings.groq_reasoning_effort,
        temperature=settings.groq_temperature,
        max_completion_tokens=settings.groq_max_completion_tokens,
        timeout_seconds=settings.groq_timeout_seconds,
    )
    model_name = settings.litellm_model if settings.litellm_enabled else settings.groq_model
    return GroqWorkflowPlanner(client, model_name=model_name), client.close
