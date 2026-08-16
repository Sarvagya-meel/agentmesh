from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, cast

import httpx

from agentmesh.registry.models import AgentCard


class BaseAgent(ABC):
    """Minimal contract for a single-agent worker in the event-driven mesh."""

    agent_name: str

    def __init__(
        self,
        agent_name: str,
        *,
        auto_register: bool = True,
        capabilities: list[str] | None = None,
        skills: list[str] | None = None,
        description: str | None = None,
        endpoint: str | None = None,
        owner: str = "platform-team",
    ) -> None:
        self.agent_name = agent_name
        self.capabilities = capabilities or []
        self.skills = skills or []
        self.description = description or f"{self.agent_name} agent"
        self.endpoint = endpoint or os.getenv("AGENT_ENDPOINT", "http://localhost:8001")
        self.owner = owner
        self.auto_register = auto_register and os.getenv(
            "AUTO_REGISTER_AGENTS", "true"
        ).lower() in {"1", "true", "yes"}
        if self.auto_register:
            self.register_self(
                endpoint=endpoint,
                capabilities=self.capabilities,
                skills=self.skills,
                description=self.description,
                owner=owner,
            )

    def register_self(
        self,
        *,
        endpoint: str | None = None,
        capabilities: list[str] | None = None,
        skills: list[str] | None = None,
        description: str | None = None,
        owner: str = "platform-team",
    ) -> dict[str, Any] | None:
        registry_url = os.getenv("AGENT_REGISTRY_URL", "http://127.0.0.1:8000/registry/agents")
        payload = self.agent_card(
            endpoint=endpoint,
            capabilities=capabilities,
            skills=skills,
            description=description,
            owner=owner,
        ).model_dump(mode="json")

        try:
            response = httpx.post(registry_url, json=payload, timeout=3.0)
            if response.status_code in {200, 201}:
                return cast(dict[str, Any], response.json())
        except httpx.HTTPError:
            return None
        return None

    def agent_card(
        self,
        *,
        endpoint: str | None = None,
        capabilities: list[str] | None = None,
        skills: list[str] | None = None,
        description: str | None = None,
        owner: str | None = None,
    ) -> AgentCard:
        """Return the dynamic registry card advertised by this worker."""

        return AgentCard(
            agent_id=self.agent_name,
            name=self.agent_name,
            version="1.0.0",
            description=description or self.description,
            endpoint=endpoint or self.endpoint,
            capabilities=capabilities if capabilities is not None else self.capabilities,
            skills=skills if skills is not None else self.skills,
            owner=owner or self.owner,
            status="online",
        )

    @abstractmethod
    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's assigned unit of work and return a result payload."""

    def handle_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compatibility hook for the polling loop used by concrete agent implementations."""
        return self.run_task(payload)
