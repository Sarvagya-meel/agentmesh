from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.agent_langgraph_orchestrator_supervisor.planner import (
    CapabilityWorkflowPlanner,
    LLMWorkflowPlanner,
    WorkflowPlanner,
)
from agentmesh.core.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.providers.litellm import LiteLLMStructuredOutputClient


def create_workflow_planner(
    settings: Settings,
) -> tuple[WorkflowPlanner, Callable[[], None]]:
    """Create the configured planning brain and its cleanup callback."""

    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return CapabilityWorkflowPlanner(), lambda: None
    if provider != "litellm":
        raise ValidationError("LLM_PROVIDER must be mock or litellm for orchestration.")

    api_key = settings.litellm_master_key.get_secret_value().strip()
    if not api_key:
        raise ValidationError(
            "LITELLM_MASTER_KEY is required when LLM_PROVIDER=litellm."
        )

    client = LiteLLMStructuredOutputClient(
        api_key=api_key,
        model=settings.litellm_model,
        api_base=settings.litellm_api_base,
        reasoning_effort=settings.llm_reasoning_effort,
        temperature=settings.llm_temperature,
        max_completion_tokens=settings.llm_max_completion_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return LLMWorkflowPlanner(client, model_name=settings.litellm_model), client.close
