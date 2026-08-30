from __future__ import annotations

from uuid import UUID

from agentmesh.core.models import Event, EventFilters, validate_event
from agentmesh.core.observability import agentmesh_metadata, agentmesh_run_name, agentmesh_span
from agentmesh.services.service_agentmesh_server.database.repository import EventRepository


class EventService:
    """Validate and append events to the AgentMesh source-of-truth log."""

    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    def append(self, event: Event, *, known_agents: set[str] | None = None) -> Event:
        """Validate and idempotently append one immutable event."""

        metadata = agentmesh_metadata(
            workflow_id=event.workflow_id,
            conversation_id=event.conversation_id,
            event_id=event.event_id,
            event_type=event.event_type,
            source_agent=event.source_agent,
            target_agent=event.target_agent,
            causation_id=event.causation_id,
            routing_mode=event.routing_mode,
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                event.workflow_id,
                f"event {event.event_type}",
                event.source_agent,
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

        events = self.repository.list_pending_assignments(agent_id, limit=limit)
        if not events:
            return events
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                events[0].workflow_id,
                "assignment queue list",
                agent_id,
            ),
            inputs={"agent_id": agent_id, "limit": limit},
            metadata=agentmesh_metadata(
                agent_id=agent_id,
                workflow_id=events[0].workflow_id,
                limit=limit,
            ),
            tags=["assignments", "queue"],
        ) as run:
            if run is not None:
                run.end(outputs={"assignment_count": len(events)})
        return events

    def replay(self, workflow_id: UUID) -> list[Event]:
        """Return the complete ordered event history for a workflow."""

        return self.repository.query(EventFilters(workflow_id=workflow_id, limit=10_000))
