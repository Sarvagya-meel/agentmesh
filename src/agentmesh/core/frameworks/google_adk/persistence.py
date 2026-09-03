"""Create native Google ADK session services for AgentMesh agents."""

from __future__ import annotations

from google.adk.sessions import BaseSessionService, DatabaseSessionService, InMemorySessionService

from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.observability import agentmesh_metadata, agentmesh_run_name, agentmesh_span


def google_adk_database_url(database_url: str) -> str:
    """Select ADK's installed asyncpg SQLAlchemy driver for PostgreSQL."""

    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


def create_google_adk_session_service(settings: Settings) -> BaseSessionService:
    """Create the configured ADK session service using native ADK persistence."""

    backend = settings.google_adk_session_backend.strip().lower()
    if backend == "memory":
        with agentmesh_span(
            agentmesh_run_name("CheckPointer", "google-adk-memory", "session setup", "system"),
            metadata=agentmesh_metadata(
                checkpoint_backend="google_adk_memory",
                checkpoint_operation="session_setup",
                framework="google_adk",
            ),
            tags=["checkpoint", "google-adk", "setup"],
        ):
            return InMemorySessionService()
    if backend not in {"database", "postgres"}:
        raise ValidationError("GOOGLE_ADK_SESSION_BACKEND must be memory, database, or postgres.")
    try:
        with agentmesh_span(
            agentmesh_run_name(
                "CheckPointer",
                "google-adk-database",
                "session setup",
                "system",
            ),
            metadata=agentmesh_metadata(
                checkpoint_backend="google_adk_database",
                checkpoint_operation="session_setup",
                framework="google_adk",
            ),
            tags=["checkpoint", "google-adk", "database", "setup"],
        ):
            return DatabaseSessionService(db_url=google_adk_database_url(settings.database_url))
    except (ImportError, ValueError) as exc:
        raise ValidationError(
            "Google ADK database sessions require the ADK database dependencies."
        ) from exc
