from __future__ import annotations

from agentmesh.agents.common.contracts.exceptions import ValidationError
from agentmesh.agents.common.providers.groq import GroqStructuredOutputClient
from agentmesh.config import Settings


def create_groq_client(settings: Settings) -> GroqStructuredOutputClient:
    """Create the shared Groq client used by text-generating agents."""

    if settings.llm_provider.strip().lower() != "groq":
        raise ValidationError("Worker LLM_PROVIDER must be mock or groq.")
    return GroqStructuredOutputClient(
        api_key=groq_api_key(settings),
        model=settings.groq_model,
        api_base=settings.groq_api_base,
        reasoning_effort=settings.groq_reasoning_effort,
        temperature=settings.groq_temperature,
        max_completion_tokens=settings.groq_max_completion_tokens,
        timeout_seconds=settings.groq_timeout_seconds,
    )


def groq_api_key(settings: Settings) -> str:
    """Return the configured Groq key or raise a domain validation error."""

    if settings.llm_provider.strip().lower() != "groq":
        raise ValidationError("Worker LLM_PROVIDER must be mock or groq.")
    api_key = (
        settings.groq_api_key.get_secret_value().strip()
        if settings.groq_api_key is not None
        else ""
    )
    if not api_key:
        raise ValidationError("GROQ_API_KEY is required when LLM_PROVIDER=groq.")
    return api_key
