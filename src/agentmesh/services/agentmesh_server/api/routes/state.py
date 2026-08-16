from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from agentmesh.agents.common.contracts.models import WorkflowState
from agentmesh.services.agentmesh_server.api.dependencies import get_state_service
from agentmesh.services.agentmesh_server.events.state import StateService

router = APIRouter(prefix="/state", tags=["state"])


@router.get("/{workflow_id}", response_model=WorkflowState)
def get_workflow_state(
    workflow_id: UUID,
    service: Annotated[StateService, Depends(get_state_service)],
) -> WorkflowState:
    return service.get_current(workflow_id)
