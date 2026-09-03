"""Create native LangGraph checkpointers for any AgentMesh component."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.observability import agentmesh_metadata, agentmesh_run_name, agentmesh_span

POSTGRES_SETUP_LOCK = 193576485


@contextmanager
def _postgres_setup_lock(url: str) -> Iterator[None]:
    import psycopg

    # A separate session lock also covers DDL that cannot run in a transaction.
    # Closing this connection releases the lock on success, failure, or cancellation.
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET lock_timeout = '90s'")
        connection.execute("SELECT pg_advisory_lock(%s)", (POSTGRES_SETUP_LOCK,))
        yield


@asynccontextmanager
async def _async_postgres_setup_lock(url: str) -> AsyncIterator[None]:
    import psycopg

    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        await connection.execute("SET lock_timeout = '90s'")
        await connection.execute("SELECT pg_advisory_lock(%s)", (POSTGRES_SETUP_LOCK,))
        yield


def create_langgraph_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], None]]:
    """Create the configured LangGraph checkpointer and cleanup callback."""

    backend = settings.langgraph_checkpoint_backend.strip().lower()
    if backend == "memory":
        with agentmesh_span(
            agentmesh_run_name("CheckPointer", "memory", "setup", "system"),
            metadata=agentmesh_metadata(
                checkpoint_backend="memory",
                checkpoint_operation="setup",
            ),
            tags=["checkpoint", "setup"],
        ):
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
    with agentmesh_span(
        agentmesh_run_name("CheckPointer", "postgres", "setup", "system"),
        metadata=agentmesh_metadata(
            checkpoint_backend="postgres",
            checkpoint_operation="setup",
        ),
        tags=["checkpoint", "postgres", "setup"],
    ):
        checkpointer = PostgresSaver(connection)
        try:
            with _postgres_setup_lock(url):
                checkpointer.setup()
        except BaseException:
            connection.close()
            raise
        return checkpointer, connection.close


async def create_async_langgraph_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], Awaitable[None]]]:
    """Create a checkpointer that implements LangGraph's native async contract."""

    backend = settings.langgraph_checkpoint_backend.strip().lower()
    if backend == "memory":

        async def close_memory() -> None:
            return None

        with agentmesh_span(
            agentmesh_run_name("CheckPointer", "memory", "async setup", "system"),
            metadata=agentmesh_metadata(
                checkpoint_backend="memory",
                checkpoint_operation="setup",
            ),
            tags=["checkpoint", "setup"],
        ):
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
    with agentmesh_span(
        agentmesh_run_name("CheckPointer", "postgres", "async setup", "system"),
        metadata=agentmesh_metadata(
            checkpoint_backend="postgres",
            checkpoint_operation="setup",
        ),
        tags=["checkpoint", "postgres", "setup"],
    ):
        checkpointer = await context_manager.__aenter__()
        try:
            async with _async_postgres_setup_lock(url):
                await checkpointer.setup()
        except BaseException:
            await context_manager.__aexit__(None, None, None)
            raise

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
    try:
        with _postgres_setup_lock(url):
            store.setup()
    except BaseException:
        context_manager.__exit__(None, None, None)
        raise

    def close() -> None:
        context_manager.__exit__(None, None, None)

    return store, close
