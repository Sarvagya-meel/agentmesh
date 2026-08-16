from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.common.agent_models import BaseAgent
from agentmesh.agents.common.providers import create_groq_client
from agentmesh.agents.langgraph_copilot.agent import ConversationAgent
from agentmesh.config import Settings


def create_langgraph_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the LangGraph worker with the configured model provider."""

    if settings.llm_provider.strip().lower() == "mock":
        return ConversationAgent(auto_register=False), lambda: None
    client = create_groq_client(settings)
    return ConversationAgent(auto_register=False, llm_client=client), client.close
