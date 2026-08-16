from __future__ import annotations

from datetime import UTC, datetime

from agentmesh.core.exceptions import AgentRegistryError
from agentmesh.registry.models import AgentCard
from agentmesh.registry.repository import RegistryRepository


class RegistryService:
    """Discovery service that keeps dynamic agent metadata available to orchestrators."""

    def __init__(self, repository: RegistryRepository) -> None:
        self.repository = repository

    def register_agent(self, card: AgentCard) -> AgentCard:
        existing = self.repository.get(card.agent_id)
        if existing is not None and existing.status == "online":
            raise AgentRegistryError(f"Agent {card.agent_id!r} is already registered.")
        card.last_seen = datetime.now(UTC)
        return self.repository.register(card)

    def heartbeat(self, agent_id: str) -> AgentCard:
        card = self.repository.get(agent_id)
        if card is None:
            raise AgentRegistryError(f"Agent {agent_id!r} not found in the registry.")
        card.last_seen = datetime.now(UTC)
        card.status = "online"
        return card

    def list_agents(self) -> list[AgentCard]:
        return self.repository.list_agents()

    def get_agent(self, agent_id: str) -> AgentCard | None:
        return self.repository.get(agent_id)

    def find_capable_agents(self, capability: str) -> list[AgentCard]:
        return self.repository.find_by_capability(capability)

    def deregister_agent(self, agent_id: str) -> bool:
        return self.repository.remove(agent_id)
