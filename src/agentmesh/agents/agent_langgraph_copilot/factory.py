from __future__ import annotations

from collections.abc import Awaitable, Callable

from agentmesh.agents.agent_langgraph_copilot.agent import ConversationAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.config import Settings
from agentmesh.core.frameworks.langgraph import (
    create_async_langgraph_checkpointer,
    create_langgraph_store,
)
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.providers import create_groq_client


async def create_langgraph_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], Awaitable[None]]]:
    """Build the LangGraph worker with the configured model provider."""

    checkpointer, close_checkpointer = await create_async_langgraph_checkpointer(settings)
    store, close_store = create_langgraph_store(settings)
    provider = settings.llm_provider.strip().lower()
    if provider == "mock":

        async def close_mock() -> None:
            close_store()
            await close_checkpointer()

        return (
            ConversationAgent(
                auto_register=False,
                checkpointer=checkpointer,
                store=store,
                long_term_memory_enabled=settings.langgraph_long_term_memory_enabled,
                memory_retention_days=settings.langgraph_memory_retention_days,
            ),
            close_mock,
        )
    try:
        client = create_groq_client(settings)
    except ValidationError:
        close_store()
        await close_checkpointer()
        raise

    async def close_live() -> None:
        client.close()
        close_store()
        await close_checkpointer()

    return (
        ConversationAgent(
            auto_register=False,
            llm_client=client,
            checkpointer=checkpointer,
            store=store,
            long_term_memory_enabled=settings.langgraph_long_term_memory_enabled,
            memory_retention_days=settings.langgraph_memory_retention_days,
        ),
        close_live,
    )
