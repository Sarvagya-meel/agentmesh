from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import AgentRegistryError
from agentmesh.core.observability import (
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
    resolve_trace_author,
    trace_author_metadata,
)
from agentmesh.services.service_agentmesh_server.registry.repository import RegistryRepository


class RegistryService:
    """Discovery service that keeps dynamic agent metadata available to orchestrators."""

    def __init__(
        self,
        repository: RegistryRepository,
        *,
        stale_seconds: float = 180.0,
        resource_repository: PostgresResourceRepository | None = None,
    ) -> None:
        self.repository = repository
        self.stale_seconds = stale_seconds
        self.resource_repository = resource_repository

    def register_agent(self, card: AgentCard) -> AgentCard:
        author = resolve_trace_author("agentmesh-registry")
        with agentmesh_span(
            agentmesh_run_name("Registry", card.agent_id, "register agent", author.author_name),
            inputs={"agent_id": card.agent_id, "capabilities": card.capabilities},
            metadata=agentmesh_metadata(
                agent_id=card.agent_id,
                agent_name=card.name,
                author_target_name=card.name,
                registry_operation="register",
                execution_mode="registry",
                **trace_author_metadata(author),
            ),
            tags=["registry", card.agent_id],
        ) as run:
            existing = self.repository.get(card.agent_id)
            if existing is not None and existing.status == "online":
                raise AgentRegistryError(f"Agent {card.agent_id!r} is already registered.")
            card.last_seen = datetime.now(UTC)
            registered = self.repository.register(card)
            if run is not None:
                run.end(outputs={"status": registered.status})
            return registered

    def upsert_agent(self, card: AgentCard) -> AgentCard:
        author = resolve_trace_author("agentmesh-registry")
        with agentmesh_span(
            agentmesh_run_name("Registry", card.agent_id, "upsert agent", author.author_name),
            inputs={"agent_id": card.agent_id, "capabilities": card.capabilities},
            metadata=agentmesh_metadata(
                agent_id=card.agent_id,
                agent_name=card.name,
                author_target_name=card.name,
                registry_operation="upsert",
                execution_mode="registry",
                **trace_author_metadata(author),
            ),
            tags=["registry", card.agent_id],
        ) as run:
            card.last_seen = datetime.now(UTC)
            registered = self.repository.register(card)
            if run is not None:
                run.end(outputs={"status": registered.status})
            return registered

    def heartbeat(self, agent_id: str, telemetry: dict[str, Any] | None = None) -> AgentCard:
        safe_telemetry = telemetry or {}
        card = self.repository.get(agent_id)
        if card is None:
            raise AgentRegistryError(f"Agent {agent_id!r} not found in the registry.")
        card.last_seen = datetime.now(UTC)
        if self.resource_repository is None:
            runtime_status = str(safe_telemetry.get("runtime_status", "READY")).upper()
            card.status = {
                "STARTING": "starting",
                "READY": "online",
                "DEGRADED": "degraded",
                "DRAINING": "draining",
                "OFFLINE": "offline",
            }.get(runtime_status, "degraded")
            card.metadata = {**card.metadata, **safe_telemetry}
        return self.repository.register(card)

    def list_agents(self) -> list[AgentCard]:
        author = resolve_trace_author("agentmesh-registry")
        with agentmesh_span(
            agentmesh_run_name("Registry", "registry", "list agents", author.author_name),
            metadata=agentmesh_metadata(
                registry_operation="list_agents",
                execution_mode="registry",
                **trace_author_metadata(author),
            ),
            tags=["registry", "list"],
        ) as run:
            self.mark_stale_agents()
            cards = [self._aggregate_card(card) for card in self.repository.list_agents()]
            if run is not None:
                run.end(outputs={"agent_count": len(cards)})
            return cards

    def get_agent(self, agent_id: str) -> AgentCard | None:
        self.mark_stale_agents()
        card = self.repository.get(agent_id)
        return self._aggregate_card(card) if card is not None else None

    def find_capable_agents(self, capability: str) -> list[AgentCard]:
        cards = [
            self._aggregate_card(card) for card in self.repository.find_by_capability(capability)
        ]
        return [
            card
            for card in cards
            if card.status == "online" and bool(card.metadata.get("assignment_ready", True))
        ]

    def list_resources(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self.resource_repository is None:
            return []
        return self.resource_repository.list_resources(limit=limit)

    def list_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self.resource_repository is None:
            return []
        return self.resource_repository.list_audit_events(limit=limit)

    def deregister_agent(self, agent_id: str) -> bool:
        return self.repository.remove(agent_id)

    def mark_stale_agents(self) -> list[str]:
        author = resolve_trace_author("agentmesh-registry")
        if self.resource_repository is not None:
            stale_runtime_ids = self.resource_repository.mark_stale_runtime_instances(
                stale_seconds=self.stale_seconds,
                trace=False,
            )
            if stale_runtime_ids:
                with agentmesh_span(
                    agentmesh_run_name(
                        "Registry",
                        "agent-runtimes",
                        "status transition stale",
                        author.author_name,
                    ),
                    inputs={"stale_runtime_ids": stale_runtime_ids},
                    metadata=agentmesh_metadata(
                        registry_operation="mark_stale_runtime_instances",
                        stale_runtime_count=len(stale_runtime_ids),
                        execution_mode="registry",
                        **trace_author_metadata(author),
                    ),
                    tags=["registry", "status-transition"],
                ):
                    pass
            for card in self.repository.list_agents():
                self.repository.register(self._aggregate_card(card))
            return [
                card.agent_id for card in self.repository.list_agents() if card.status == "stale"
            ]
        cutoff = datetime.now(UTC) - timedelta(seconds=self.stale_seconds)
        stale_ids: list[str] = []
        for card in self.repository.list_agents():
            last_seen = card.last_seen
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            if card.status not in {"offline", "stale"} and last_seen < cutoff:
                card.status = "stale"
                card.metadata = {**card.metadata, "runtime_status": "OFFLINE"}
                self.repository.register(card)
                stale_ids.append(card.agent_id)
        if stale_ids:
            with agentmesh_span(
                agentmesh_run_name(
                    "Registry",
                    "agents",
                    "status transition stale",
                    author.author_name,
                ),
                inputs={"stale_agent_ids": stale_ids},
                metadata=agentmesh_metadata(
                    registry_operation="mark_stale_agents",
                    stale_agent_count=len(stale_ids),
                    execution_mode="registry",
                    **trace_author_metadata(author),
                ),
                tags=["registry", "status-transition"],
            ):
                pass
        return stale_ids

    def is_assignment_ready(self, agent_id: str) -> bool:
        card = self.get_agent(agent_id)
        return bool(
            card and card.status == "online" and card.metadata.get("assignment_ready", True)
        )

    def _aggregate_card(self, card: AgentCard) -> AgentCard:
        if (
            self.resource_repository is None
            or card.metadata.get("runtime_model") != "multi-instance"
        ):
            return card
        availability = self.resource_repository.runtime_availability(
            card.agent_id,
            stale_seconds=self.stale_seconds,
        )
        is_available = bool(availability["direct_ready"] or availability["assignment_ready"])
        endpoint = availability["direct_endpoint"] or card.endpoint
        last_seen = availability.pop("last_seen", None) or card.last_seen
        return card.model_copy(
            update={
                "status": "online" if is_available else "stale",
                "endpoint": endpoint,
                "last_seen": last_seen,
                "metadata": {**card.metadata, **availability},
            }
        )
