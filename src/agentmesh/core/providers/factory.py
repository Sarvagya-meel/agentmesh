from __future__ import annotations

from agentmesh.core.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.providers.litellm import LiteLLMStructuredOutputClient


def create_litellm_client(settings: Settings) -> LiteLLMStructuredOutputClient:
    """Create the shared OpenAI-compatible client through LiteLLM Gateway."""

    if settings.llm_provider.strip().lower() != "litellm":
        raise ValidationError("Worker LLM_PROVIDER must be mock or litellm.")
    api_key = settings.litellm_master_key.get_secret_value().strip()
    if not api_key:
        raise ValidationError("LITELLM_MASTER_KEY is required when LLM_PROVIDER=litellm.")
    return LiteLLMStructuredOutputClient(
        api_key=api_key,
        model=settings.litellm_model,
        api_base=settings.litellm_api_base,
        reasoning_effort=settings.llm_reasoning_effort,
        temperature=settings.llm_temperature,
        max_completion_tokens=settings.llm_max_completion_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )

