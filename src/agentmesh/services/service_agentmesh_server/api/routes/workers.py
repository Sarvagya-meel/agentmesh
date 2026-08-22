from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from agentmesh.core.models import AssignmentClaim, Event
from agentmesh.services.service_agentmesh_server.api.dependencies import get_worker_service
from agentmesh.services.service_agentmesh_server.api.schemas import (
    DirectedAssignmentRequest,
    WorkerClaimRequest,
    WorkerLeaseRenewRequest,
    WorkerResultRequest,
    WorkflowExecutionResponse,
)
from agentmesh.services.service_agentmesh_server.workers.service import WorkerService

router = APIRouter(prefix="/workers", tags=["workers"])


@router.post(
    "/{agent_id}/assignments",
    response_model=WorkflowExecutionResponse,
    status_code=202,
)
def submit_directed_assignment(
    agent_id: str,
    body: DirectedAssignmentRequest,
    service: Annotated[WorkerService, Depends(get_worker_service)],
) -> dict[str, Any]:
    return service.submit_directed_assignment(
        agent_id,
        message=body.message,
        conversation_id=body.conversation_id,
        thread_id=body.thread_id,
        user_id=body.user_id,
    )


@router.get("/{agent_id}/assignments", response_model=list[Event])
def list_assignments(
    agent_id: str,
    service: Annotated[WorkerService, Depends(get_worker_service)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Event]:
    return service.list_assignments(agent_id, limit=limit)


@router.post(
    "/{agent_id}/assignments/{event_id}/claim",
    response_model=AssignmentClaim,
)
def claim_assignment(
    agent_id: str,
    event_id: UUID,
    body: WorkerClaimRequest,
    service: Annotated[WorkerService, Depends(get_worker_service)],
) -> AssignmentClaim:
    return service.claim_assignment(event_id, agent_id=agent_id, worker_id=body.worker_id)


@router.post(
    "/{agent_id}/assignments/{event_id}/renew",
    response_model=AssignmentClaim,
)
def renew_assignment(
    agent_id: str,
    event_id: UUID,
    body: WorkerLeaseRenewRequest,
    service: Annotated[WorkerService, Depends(get_worker_service)],
) -> AssignmentClaim:
    return service.renew_claim(
        event_id,
        agent_id=agent_id,
        worker_id=body.worker_id,
        claim_token=body.claim_token,
    )


@router.post(
    "/{agent_id}/assignments/{event_id}/result",
    response_model=WorkflowExecutionResponse,
)
async def submit_assignment_result(
    agent_id: str,
    event_id: UUID,
    body: WorkerResultRequest,
    service: Annotated[WorkerService, Depends(get_worker_service)],
) -> dict[str, Any]:
    return await service.submit_result(
        event_id,
        agent_id=agent_id,
        worker_id=body.worker_id,
        claim_token=body.claim_token,
        status=body.status,
        result=body.result,
    )
