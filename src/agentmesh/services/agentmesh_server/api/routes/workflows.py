from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from agentmesh.agents.orchestrator_supervisor import MasterOrchestratorAgent
from agentmesh.services.agentmesh_server.api.dependencies import get_master_orchestrator
from agentmesh.services.agentmesh_server.api.schemas import (
    HumanDecisionRequest,
    StartWorkflowRequest,
    WorkflowExecutionResponse,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/start", response_model=WorkflowExecutionResponse, status_code=201)
def start_workflow(
    body: StartWorkflowRequest,
    orchestrator: Annotated[MasterOrchestratorAgent, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return orchestrator.start_workflow(
        body.conversation_id,
        body.goal,
        workflow_id=body.workflow_id,
        preferred_agent_ids=body.preferred_agent_ids,
    )


@router.get("/{workflow_id}", response_model=WorkflowExecutionResponse)
def get_workflow(
    workflow_id: UUID,
    orchestrator: Annotated[MasterOrchestratorAgent, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return orchestrator.get_workflow(workflow_id)


@router.post("/{workflow_id}/approvals", response_model=WorkflowExecutionResponse)
def submit_approval(
    workflow_id: UUID,
    body: HumanDecisionRequest,
    orchestrator: Annotated[MasterOrchestratorAgent, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return orchestrator.submit_human_decision(
        workflow_id,
        decision=body.decision,
        feedback=body.feedback,
        actor=body.actor,
        edits=body.edits,
    )
