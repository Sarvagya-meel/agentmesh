from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from agentmesh.core.models import Event
from agentmesh.services.service_agentmesh_server.api.dependencies import get_event_service
from agentmesh.services.service_agentmesh_server.events.service import EventService

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[Event])
def list_workflow_events(
    workflow_id: UUID,
    service: Annotated[EventService, Depends(get_event_service)],
) -> list[Event]:
    return service.replay(workflow_id)
