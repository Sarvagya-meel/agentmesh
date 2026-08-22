"""Compatibility aliases for the framework-owned LangGraph persistence factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from agentmesh.config import Settings
from agentmesh.core.frameworks.langgraph import create_langgraph_checkpointer


def create_orchestration_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], None]]:
    """Compatibility wrapper; use create_langgraph_checkpointer instead."""

    return create_langgraph_checkpointer(settings)


def create_agent_checkpointer(
    settings: Settings,
) -> tuple[BaseCheckpointSaver[Any], Callable[[], None]]:
    """Compatibility wrapper; use create_langgraph_checkpointer instead."""

    return create_langgraph_checkpointer(settings)
