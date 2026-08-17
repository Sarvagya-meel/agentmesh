from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agentmesh.config import Settings
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import ValidationError


class RegistryRepository(ABC):
    """Storage abstraction for agent discovery metadata."""

    @abstractmethod
    def register(self, card: AgentCard) -> AgentCard:
        raise NotImplementedError

    @abstractmethod
    def get(self, agent_id: str) -> AgentCard | None:
        raise NotImplementedError

    @abstractmethod
    def list_agents(self) -> list[AgentCard]:
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

    def list_agents(self) -> list[AgentCard]:
        return list(self._agents.values())

    def remove(self, agent_id: str) -> bool:
        return self._agents.pop(agent_id, None) is not None

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        target = capability.strip().lower()
        return [
            card
            for card in self._agents.values()
            if target in {item.strip().lower() for item in card.capabilities}
        ]


class PostgresRegistryRepository(RegistryRepository):
    """PostgreSQL-backed registry using the compatibility agent card table."""

    def __init__(self, connection: Connection[dict[str, Any]]) -> None:
        self._connection = connection

    @classmethod
    def from_connection_url(cls, connection_url: str) -> PostgresRegistryRepository:
        connection = psycopg.connect(
            connection_url.replace("postgresql+asyncpg://", "postgresql://", 1),
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def register(self, card: AgentCard) -> AgentCard:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agentmesh_agents (
                    agent_id, name, version, description, endpoint, capabilities,
                    skills, owner, status, metadata, registered_at, last_seen, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (agent_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    version = EXCLUDED.version,
                    description = EXCLUDED.description,
                    endpoint = EXCLUDED.endpoint,
                    capabilities = EXCLUDED.capabilities,
                    skills = EXCLUDED.skills,
                    owner = EXCLUDED.owner,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata,
                    last_seen = EXCLUDED.last_seen,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
                """,
                (
                    card.agent_id,
                    card.name,
                    card.version,
                    card.description,
                    card.endpoint,
                    Jsonb(card.capabilities),
                    Jsonb(card.skills),
                    card.owner,
                    card.status,
                    Jsonb(card.metadata),
                    card.registered_at,
                    card.last_seen,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL did not return the registered agent.")
        return self._to_agent_card(row)

    def get(self, agent_id: str) -> AgentCard | None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM agentmesh_agents WHERE agent_id = %s", (agent_id,))
            row = cursor.fetchone()
        return self._to_agent_card(row) if row is not None else None

    def list_agents(self) -> list[AgentCard]:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM agentmesh_agents ORDER BY agent_id")
            rows = cursor.fetchall()
        return [self._to_agent_card(row) for row in rows]

    def remove(self, agent_id: str) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute("DELETE FROM agentmesh_agents WHERE agent_id = %s", (agent_id,))
            return cursor.rowcount > 0

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        target = capability.strip().lower()
        return [
            card
            for card in self.list_agents()
            if target in {item.strip().lower() for item in card.capabilities}
        ]

    @staticmethod
    def _to_agent_card(row: dict[str, Any]) -> AgentCard:
        return AgentCard.model_validate(row)


def create_registry_repository(
    settings: Settings,
) -> tuple[RegistryRepository, Callable[[], None]]:
    """Create the configured registry repository and cleanup callback."""

    backend = settings.registry_backend.strip().lower()
    if backend == "memory":
        return InMemoryRegistryRepository(), lambda: None
    if backend != "postgres":
        raise ValidationError("REGISTRY_BACKEND must be memory or postgres.")
    repository = PostgresRegistryRepository.from_connection_url(settings.database_url)
    return repository, repository.close
