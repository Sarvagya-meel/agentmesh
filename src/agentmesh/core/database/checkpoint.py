"""LangGraph checkpoint factory — memory or PostgreSQL backend."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError


def create_orchestration_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], None]]:
    """Create the configured graph checkpointer and its cleanup callback."""
    backend = settings.orchestrator_checkpoint_backend.strip().lower()
    if backend == "memory":
        return MemorySaver(), lambda: None
    if backend != "postgres":
        raise ValidationError("ORCHESTRATOR_CHECKPOINT_BACKEND must be memory or postgres.")

    try:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise ValidationError(
            "Postgres checkpoints require the langgraph-checkpoint-postgres package."
        ) from exc

    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    connection = psycopg.connect(
        url, autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    checkpointer = PostgresSaver(connection)
    checkpointer.setup()
    return checkpointer, connection.close
