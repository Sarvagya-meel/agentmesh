from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from typing import Any, Literal

from agentmesh.config import Settings

SECRET_METADATA_KEYS = {"api_key", "claim_token", "token", "secret", "password"}
MAX_RUN_NAME_FIELD_LENGTH = 80


def configure_langsmith(settings: Settings) -> None:
    """Make outbound LangSmith tracing an explicit, disabled-by-default choice."""

    api_key = (
        settings.langsmith_api_key.get_secret_value()
        if settings.langsmith_api_key is not None
        else os.environ.get("LANGSMITH_API_KEY", "")
    )
    tracing_enabled = settings.langsmith_tracing and bool(api_key)

    os.environ["LANGSMITH_TRACING"] = "true" if tracing_enabled else "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if tracing_enabled else "false"
    if not tracing_enabled:
        return

    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_API_KEY"] = api_key
    if settings.langsmith_workspace_id:
        os.environ["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id


def agentmesh_metadata(**values: Any) -> dict[str, Any]:
    """Return LangSmith-safe metadata aligned to AgentMesh domain identifiers."""

    metadata: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        lowered = key.lower()
        if any(secret in lowered for secret in SECRET_METADATA_KEYS):
            metadata[f"{key}_present"] = bool(value)
            continue
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
        else:
            metadata[key] = str(value)
    return metadata


def agentmesh_run_name(
    mode: str,
    unique_id: Any,
    subject: str,
    request_user: str | None = None,
) -> str:
    """Format AgentMesh runs for quick scanning in LangSmith."""

    return " || ".join(
        [
            mode,
            _shorten(str(unique_id)),
            _shorten(subject),
            _shorten(request_user or "system"),
            _shorten(_timestamp()),
        ]
    )


def _shorten(value: str) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= MAX_RUN_NAME_FIELD_LENGTH:
        return cleaned
    return f"{cleaned[: MAX_RUN_NAME_FIELD_LENGTH - 3]}..."


def _timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def agentmesh_span(
    name: str,
    *,
    run_type: Literal[
        "tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"
    ] = "chain",
    inputs: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Iterator[Any]:
    """Open a LangSmith span with AgentMesh naming, falling back to a no-op locally."""

    if os.environ.get("LANGSMITH_TRACING", "").lower() != "true":
        with nullcontext() as run:
            yield run
        return
    try:
        from langsmith.run_helpers import trace
    except ImportError:
        with nullcontext() as run:
            yield run
        return

    with trace(
        name=name,
        run_type=run_type,
        inputs=dict(inputs or {}),
        metadata=dict(metadata or {}),
        tags=["agentmesh", *(tags or [])],
    ) as run:
        yield run
