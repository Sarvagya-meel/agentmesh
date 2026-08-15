from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from agentmesh.registry.models import AgentCard


class RegistryRepository(ABC):
    """Storage abstraction for agent discovery metadata."""

    @abstractmethod
    def register(self, card: AgentCard) -> AgentCard:
        raise NotImplementedError

    @abstractmethod
    def get(self, agent_id: str) -> AgentCard | None:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[AgentCard]:
        raise NotImplementedError

    @abstractmethod
    def remove(self, agent_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def find_by_capability(self, capability: str) -> list[AgentCard]:
        raise NotImplementedError


class InMemoryRegistryRepository(RegistryRepository):
    """Minimal registry store used for local development and tests."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> AgentCard:
        self._agents[card.agent_id] = card
        return card

    def get(self, agent_id: str) -> AgentCard | None:
        return self._agents.get(agent_id)

    def list(self) -> list[AgentCard]:
        return list(self._agents.values())

    def remove(self, agent_id: str) -> bool:
        return self._agents.pop(agent_id, None) is not None

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        target = capability.strip().lower()
        return [card for card in self._agents.values() if target in {item.strip().lower() for item in card.capabilities}]
