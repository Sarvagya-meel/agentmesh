from __future__ import annotations

from uuid import UUID

from agentmesh.core.models import Event, EventFilters, validate_event
from agentmesh.storage.repository import EventRepository


class EventService:
    """Validate and append events to the AgentMesh source-of-truth log."""

    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    def append(self, event: Event, *, known_agents: set[str] | None = None) -> Event:
        """Validate and idempotently append one immutable event."""

        return self.repository.append(validate_event(event, known_agents=known_agents))

    def query(self, filters: EventFilters) -> list[Event]:
        """Query events using domain filters."""

        return self.repository.query(filters)

    def get_by_id(self, event_id: UUID) -> Event | None:
        """Return one event by its immutable identifier."""

        return self.repository.get_by_id(event_id)

    def list_pending_assignments(self, agent_id: str, *, limit: int = 20) -> list[Event]:
        """Return directed assignments that do not yet have a terminal result."""

        return self.repository.list_pending_assignments(agent_id, limit=limit)

    def replay(self, workflow_id: UUID) -> list[Event]:
        """Return the complete ordered event history for a workflow."""

        return self.repository.query(EventFilters(workflow_id=workflow_id, limit=10_000))
