from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from agentmesh.core.models import Event, EventFilters, validate_event
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.observability import (
    TraceIdentity,
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
    resolve_trace_author,
    trace_author_metadata,
)
from agentmesh.services.service_agentmesh_server.database.repository import EventRepository


class EventService:
    """Validate and append events to the AgentMesh source-of-truth log."""

    def __init__(
        self,
        repository: EventRepository,
        *,
        agent_resolver: Callable[[str], AgentCard | None] | None = None,
    ) -> None:
        self.repository = repository
        self.agent_resolver = agent_resolver

    def set_agent_resolver(self, agent_resolver: Callable[[str], AgentCard | None]) -> None:
        self.agent_resolver = agent_resolver

    def append(self, event: Event, *, known_agents: set[str] | None = None) -> Event:
        """Validate and idempotently append one immutable event."""

        source_author = self._resolve_author(event.source_agent)
        target_author = self._resolve_author(event.target_agent) if event.target_agent else None
        metadata = agentmesh_metadata(
            workflow_id=event.workflow_id,
            conversation_id=event.conversation_id,
            event_id=event.event_id,
            event_type=event.event_type,
            source_agent=event.source_agent,
            source_agent_name=source_author.author_name,
            target_agent=event.target_agent,
            target_agent_name=target_author.author_name if target_author else None,
            causation_id=event.causation_id,
            routing_mode=event.routing_mode,
            **trace_author_metadata(source_author),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                event.workflow_id,
                f"event {event.event_type}",
                source_author.author_name,
            ),
            inputs={
                "payload_keys": sorted(event.payload) if isinstance(event.payload, dict) else []
            },
            metadata=metadata,
            tags=["event-log", event.event_type.lower()],
        ) as run:
            stored = self.repository.append(validate_event(event, known_agents=known_agents))
            if run is not None:
                run.end(outputs={"sequence_number": stored.sequence_number})
            return stored

    def query(self, filters: EventFilters) -> list[Event]:
        """Query events using domain filters."""

        return self.repository.query(filters)

    def get_by_id(self, event_id: UUID) -> Event | None:
        """Return one event by its immutable identifier."""

        return self.repository.get_by_id(event_id)

    def list_pending_assignments(self, agent_id: str, *, limit: int = 20) -> list[Event]:
        """Return directed assignments that do not yet have a terminal result."""

        return self.repository.list_pending_assignments(agent_id, limit=limit)

    def list_pending_supervisor_actions(
        self, supervisor_id: str, *, limit: int = 20
    ) -> list[Event]:
        """Return durable commands waiting for one supervisor runtime."""

        return self.repository.list_pending_supervisor_actions(supervisor_id, limit=limit)

    def replay(self, workflow_id: UUID) -> list[Event]:
        """Return the complete ordered event history for a workflow."""

        return self.repository.query(EventFilters(workflow_id=workflow_id, limit=10_000))

    def _resolve_author(self, agent_id: str) -> TraceIdentity:
        card = None
        if self.agent_resolver is not None:
            try:
                card = self.agent_resolver(agent_id)
            except Exception:
                card = None
        return resolve_trace_author(agent_id, agent_card=card)
