from contextlib import asynccontextmanager

import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agentmesh.config import Settings
from agentmesh.core.frameworks.langgraph import persistence


@pytest.mark.parametrize("fail", [False, True])
def test_sync_setup_lock_releases_session_even_on_failure(monkeypatch, fail):
    operations = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            operations.append("closed")

        def execute(self, sql, params=None):
            operations.append((sql, params))

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: Connection())
    try:
        with persistence._postgres_setup_lock("postgresql://test"):
            operations.append("setup")
            if fail:
                raise RuntimeError("migration failed")
    except RuntimeError:
        assert fail
    assert operations == [
        ("SET lock_timeout = '90s'", None),
        ("SELECT pg_advisory_lock(%s)", (persistence.POSTGRES_SETUP_LOCK,)),
        "setup",
        "closed",
    ]


@pytest.mark.parametrize("fail", [False, True])
async def test_async_setup_lock_uses_same_key_and_releases_session(monkeypatch, fail):
    operations = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            operations.append("closed")

        async def execute(self, sql, params=None):
            operations.append((sql, params))

    async def connect(*args, **kwargs):
        return Connection()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    try:
        async with persistence._async_postgres_setup_lock("postgresql://test"):
            operations.append("setup")
            if fail:
                raise RuntimeError("migration failed")
    except RuntimeError:
        assert fail
    assert operations == [
        ("SET lock_timeout = '90s'", None),
        ("SELECT pg_advisory_lock(%s)", (persistence.POSTGRES_SETUP_LOCK,)),
        "setup",
        "closed",
    ]


async def test_failed_async_checkpoint_setup_closes_saver_connection(monkeypatch):
    operations = []

    class Saver:
        async def setup(self):
            assert operations == ["locked"]
            raise RuntimeError("migration failed")

    @asynccontextmanager
    async def saver_connection(url):
        try:
            yield Saver()
        finally:
            operations.append("saver closed")

    @asynccontextmanager
    async def lock(url):
        operations.append("locked")
        try:
            yield
        finally:
            operations.append("unlocked")

    monkeypatch.setattr(AsyncPostgresSaver, "from_conn_string", saver_connection)
    monkeypatch.setattr(persistence, "_async_postgres_setup_lock", lock)
    with pytest.raises(RuntimeError, match="migration failed"):
        await persistence.create_async_langgraph_checkpointer(
            Settings(langgraph_checkpoint_backend="postgres")
        )
    assert operations == ["locked", "unlocked", "saver closed"]
