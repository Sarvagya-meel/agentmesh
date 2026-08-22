"""Create native LangGraph checkpointers for any AgentMesh component."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError


def create_langgraph_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], None]]:
    """Create the configured LangGraph checkpointer and cleanup callback."""

    backend = settings.langgraph_checkpoint_backend.strip().lower()
    if backend == "memory":
        return MemorySaver(), lambda: None
    if backend != "postgres":
        raise ValidationError("LANGGRAPH_CHECKPOINT_BACKEND must be memory or postgres.")

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
        url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    checkpointer = PostgresSaver(connection)
    checkpointer.setup()
    return checkpointer, connection.close


async def create_async_langgraph_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], Awaitable[None]]]:
    """Create a checkpointer that implements LangGraph's native async contract."""

    backend = settings.langgraph_checkpoint_backend.strip().lower()
    if backend == "memory":

        async def close_memory() -> None:
            return None

        return MemorySaver(), close_memory
    if backend != "postgres":
        raise ValidationError("LANGGRAPH_CHECKPOINT_BACKEND must be memory or postgres.")

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        raise ValidationError(
            "Postgres checkpoints require the langgraph-checkpoint-postgres package."
        ) from exc

    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    context_manager = AsyncPostgresSaver.from_conn_string(url)
    checkpointer = await context_manager.__aenter__()
    await checkpointer.setup()

    async def close() -> None:
        await context_manager.__aexit__(None, None, None)

    return checkpointer, close


def create_langgraph_store(
    settings: Settings,
) -> tuple[BaseStore, Callable[[], None]]:
    """Create an injected long-term Store independently from graph checkpoints."""

    backend = settings.langgraph_store_backend.strip().lower()
    if backend == "memory":
        return InMemoryStore(), lambda: None
    if backend != "postgres":
        raise ValidationError("LANGGRAPH_STORE_BACKEND must be memory or postgres.")

    try:
        from langgraph.store.postgres import PostgresStore
    except ImportError as exc:
        raise ValidationError(
            "Postgres Store memory requires langgraph-checkpoint-postgres."
        ) from exc

    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    context_manager = PostgresStore.from_conn_string(url)
    store = context_manager.__enter__()
    store.setup()

    def close() -> None:
        context_manager.__exit__(None, None, None)

    return store, close
