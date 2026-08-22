from google.adk.sessions import InMemorySessionService
from langgraph.checkpoint.memory import MemorySaver

from agentmesh.config import Settings
from agentmesh.core.frameworks.google_adk import create_google_adk_session_service
from agentmesh.core.frameworks.google_adk.persistence import google_adk_database_url
from agentmesh.core.frameworks.langgraph import create_langgraph_checkpointer


def test_langgraph_factory_creates_native_memory_checkpointer() -> None:
    checkpointer, close = create_langgraph_checkpointer(
        Settings(langgraph_checkpoint_backend="memory")
    )

    assert isinstance(checkpointer, MemorySaver)
    close()


def test_google_adk_factory_creates_native_memory_session_service() -> None:
    session_service = create_google_adk_session_service(
        Settings(google_adk_session_backend="memory")
    )

    assert isinstance(session_service, InMemorySessionService)


def test_google_adk_postgres_url_selects_asyncpg_driver() -> None:
    assert (
        google_adk_database_url("postgresql://agentmesh:secret@postgres:5432/agentmesh")
        == "postgresql+asyncpg://agentmesh:secret@postgres:5432/agentmesh"
    )
