from __future__ import annotations

from collections.abc import Callable

from agentmesh.agents.agent_langgraph_copilot.agent import ConversationAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.providers import create_groq_client


def create_langgraph_worker_agent(
    settings: Settings,
) -> tuple[BaseAgent, Callable[[], None]]:
    """Build the LangGraph worker with the configured model provider."""

    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return ConversationAgent(auto_register=False), lambda: None
    try:
        client = create_groq_client(settings)
    except ValidationError:
        return ConversationAgent(auto_register=False), lambda: None
    return ConversationAgent(auto_register=False, llm_client=client), client.close
