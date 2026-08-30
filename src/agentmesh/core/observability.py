from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Literal

from agentmesh.config import Settings

SECRET_METADATA_KEYS = {"api_key", "claim_token", "token", "secret", "password"}
MAX_RUN_NAME_FIELD_LENGTH = 80
SYSTEM_TRACE_IDENTITIES = {
    "agentmesh-registry": ("AgentMesh Registry", "registry"),
    "registry": ("AgentMesh Registry", "registry"),
    "agentmesh-control-plane": ("AgentMesh Control Plane", "control_plane"),
    "control-plane": ("AgentMesh Control Plane", "control_plane"),
    "orchestrator-supervisor-agent": ("orchestrator-supervisor-agent", "agent"),
    "system": ("system", "system"),
    "api": ("AgentMesh API", "api"),
    "request": ("request", "request"),
}


@dataclass(frozen=True)
class TraceIdentity:
    """Resolved author/resource identity for AgentMesh LangSmith metadata."""

    author_id: str
    author_name: str
    author_type: str
    author_owner: str | None = None
    resource_id: str | None = None
    runtime_instance_id: str | None = None


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


def resolve_trace_author(
    identity: Any = None,
    *,
    agent_card: Any = None,
    resource: Mapping[str, Any] | None = None,
    fallback_name: str | None = None,
    author_type: str | None = None,
) -> TraceIdentity:
    """Resolve an AgentMesh author from AgentCards/resources before raw IDs."""

    if agent_card is not None:
        metadata = getattr(agent_card, "metadata", {}) or {}
        author_id = str(getattr(agent_card, "agent_id", identity or fallback_name or "unknown"))
        return TraceIdentity(
            author_id=author_id,
            author_name=str(getattr(agent_card, "name", None) or fallback_name or author_id),
            author_type=author_type or "agent",
            author_owner=getattr(agent_card, "owner", None),
            resource_id=str(metadata.get("resource_id") or author_id),
            runtime_instance_id=_optional_str(metadata.get("runtime_instance_id")),
        )

    if resource is not None:
        metadata = resource.get("metadata", {})
        metadata = metadata if isinstance(metadata, Mapping) else {}
        resource_id = str(resource.get("resource_id") or identity or fallback_name or "unknown")
        return TraceIdentity(
            author_id=str(resource.get("agent_id") or metadata.get("agent_id") or resource_id),
            author_name=str(resource.get("name") or fallback_name or resource_id),
            author_type=author_type or str(resource.get("resource_type") or "resource"),
            author_owner=_optional_str(resource.get("owner")),
            resource_id=resource_id,
            runtime_instance_id=_optional_str(metadata.get("runtime_instance_id")),
        )

    author_id = str(identity or fallback_name or "unknown")
    system_identity = SYSTEM_TRACE_IDENTITIES.get(author_id.lower())
    if system_identity is not None:
        return TraceIdentity(
            author_id=author_id,
            author_name=system_identity[0],
            author_type=author_type or system_identity[1],
            resource_id=author_id,
        )
    return TraceIdentity(
        author_id=author_id,
        author_name=fallback_name or author_id,
        author_type=author_type or "entity",
        resource_id=author_id,
    )


def trace_author_metadata(
    author: TraceIdentity,
    *,
    prefix: str = "author",
) -> dict[str, Any]:
    """Return metadata fields for a resolved trace author."""

    values: dict[str, Any] = {
        f"{prefix}_id": author.author_id,
        f"{prefix}_name": author.author_name,
        f"{prefix}_type": author.author_type,
        f"{prefix}_owner": author.author_owner,
        f"{prefix}_resource_id": author.resource_id,
        f"{prefix}_runtime_instance_id": author.runtime_instance_id,
    }
    return agentmesh_metadata(**values)


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


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


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
