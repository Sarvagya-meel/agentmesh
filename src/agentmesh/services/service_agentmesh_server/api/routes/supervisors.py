from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from agentmesh.core.models import AssignmentClaim, Event
from agentmesh.services.service_agentmesh_server.api.dependencies import (
    get_supervisor_action_service,
)
from agentmesh.services.service_agentmesh_server.api.schemas import (
    SupervisorActionCompleteRequest,
    SupervisorActionFailureRequest,
    WorkerClaimRequest,
    WorkerLeaseRenewRequest,
)
from agentmesh.services.service_agentmesh_server.api.security import (
    require_internal_service_token,
)
from agentmesh.services.service_agentmesh_server.supervisor.service import (
    SupervisorActionService,
)

router = APIRouter(
    prefix="/supervisors",
    tags=["supervisors"],
    dependencies=[Depends(require_internal_service_token)],
)


@router.get("/{supervisor_id}/actions", response_model=list[Event])
def list_actions(
    supervisor_id: str,
    service: Annotated[SupervisorActionService, Depends(get_supervisor_action_service)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Event]:
    return service.list_actions(supervisor_id, limit=limit)


@router.post("/{supervisor_id}/actions/{action_event_id}/claim")
def claim_action(
    supervisor_id: str,
    action_event_id: UUID,
    body: WorkerClaimRequest,
    service: Annotated[SupervisorActionService, Depends(get_supervisor_action_service)],
) -> AssignmentClaim:
    return service.claim(action_event_id, supervisor_id=supervisor_id, worker_id=body.worker_id)


@router.post("/{supervisor_id}/actions/{action_event_id}/renew")
def renew_action(
    supervisor_id: str,
    action_event_id: UUID,
    body: WorkerLeaseRenewRequest,
    service: Annotated[SupervisorActionService, Depends(get_supervisor_action_service)],
) -> AssignmentClaim:
    return service.renew(
        action_event_id,
        supervisor_id=supervisor_id,
        worker_id=body.worker_id,
        claim_token=body.claim_token,
    )


@router.post("/{supervisor_id}/actions/{action_event_id}/complete")
def complete_action(
    supervisor_id: str,
    action_event_id: UUID,
    body: SupervisorActionCompleteRequest,
    service: Annotated[SupervisorActionService, Depends(get_supervisor_action_service)],
) -> Event:
    return service.complete(
        action_event_id,
        supervisor_id=supervisor_id,
        worker_id=body.worker_id,
        claim_token=body.claim_token,
        result=body.result,
    )


@router.post("/{supervisor_id}/actions/{action_event_id}/fail")
def fail_action(
    supervisor_id: str,
    action_event_id: UUID,
    body: SupervisorActionFailureRequest,
    service: Annotated[SupervisorActionService, Depends(get_supervisor_action_service)],
) -> Event:
    return service.fail(
        action_event_id,
        supervisor_id=supervisor_id,
        worker_id=body.worker_id,
        claim_token=body.claim_token,
        error_code=body.error_code,
        error_message=body.error_message,
        retryable=body.retryable,
        retry_after_seconds=body.retry_after_seconds,
    )
