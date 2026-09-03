from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from agentmesh.core.models import Event
from agentmesh.services.service_agentmesh_server.api.dependencies import (
    get_event_service,
    get_supervisor_action_service,
)
from agentmesh.services.service_agentmesh_server.api.schemas import (
    SupervisorActionEnqueueRequest,
)
from agentmesh.services.service_agentmesh_server.api.security import (
    require_internal_service_token,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.supervisor.service import (
    SupervisorActionService,
)

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_service_token)],
)


@router.post("/events", response_model=Event, status_code=201)
def append_event(
    event: Event,
    service: Annotated[EventService, Depends(get_event_service)],
) -> Event:
    return service.append(event)


@router.post("/supervisor-actions/{supervisor_id}", response_model=Event, status_code=202)
def enqueue_supervisor_action(
    supervisor_id: str,
    body: SupervisorActionEnqueueRequest,
    service: Annotated[SupervisorActionService, Depends(get_supervisor_action_service)],
) -> Event:
    return service.enqueue(
        conversation_id=body.conversation_id,
        workflow_id=body.workflow_id,
        action_type=body.action_type,
        arguments=body.arguments,
        supervisor_id=supervisor_id,
        action_event_id=body.action_event_id,
    )
