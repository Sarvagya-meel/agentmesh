from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Minimal contract for a single-agent worker in the event-driven mesh."""

    agent_name: str

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name

    @abstractmethod
    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's assigned unit of work and return a result payload."""

    def handle_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compatibility hook for the polling loop used by concrete agent implementations."""
        return self.run_task(payload)
