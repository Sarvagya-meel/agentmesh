from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from agentmesh.services.service_agentmesh_server.api.dependencies import get_master_orchestrator
from agentmesh.services.service_agentmesh_server.api.schemas import (
    CheckpointReplayRequest,
    HumanDecisionRequest,
    StartWorkflowRequest,
    WorkflowExecutionResponse,
    WorkflowForkRequest,
)
from agentmesh.services.service_agentmesh_server.orchestration import WorkflowOrchestrator

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/graph/mermaid", response_class=PlainTextResponse)
def workflow_graph(
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> str:
    return orchestrator.graph_mermaid()


@router.get("/{workflow_id}/checkpoints")
async def workflow_checkpoints(
    workflow_id: UUID,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> list[dict[str, Any]]:
    return await orchestrator.checkpoint_history(workflow_id)


@router.post("/{workflow_id}/replay")
async def replay_workflow_checkpoint(
    workflow_id: UUID,
    body: CheckpointReplayRequest,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.replay_checkpoint(workflow_id, body.checkpoint_id)


@router.post("/{workflow_id}/fork")
async def fork_workflow_checkpoint(
    workflow_id: UUID,
    body: WorkflowForkRequest,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.fork_checkpoint(
        workflow_id,
        body.checkpoint_id,
        new_workflow_id=body.new_workflow_id,
        state_updates=body.state_updates,
    )


@router.post("/start", response_model=WorkflowExecutionResponse, status_code=201)
async def start_workflow(
    body: StartWorkflowRequest,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.astart_workflow(
        body.conversation_id,
        body.goal,
        workflow_id=body.workflow_id,
        preferred_agent_ids=body.preferred_agent_ids,
        memory_user_id=body.memory_user_id,
        memory_opt_in=body.memory_opt_in,
        memory_updates=body.memory_updates,
        memory_delete_keys=body.memory_delete_keys,
        trace_metadata={
            "trigger_source": "api",
            "trigger_route": "POST /workflows/start",
            "execution_mode": "workflow",
        },
    )


@router.get("/{workflow_id}", response_model=WorkflowExecutionResponse)
def get_workflow(
    workflow_id: UUID,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return orchestrator.get_workflow(workflow_id)


@router.post("/{workflow_id}/approvals", response_model=WorkflowExecutionResponse)
async def submit_approval(
    workflow_id: UUID,
    body: HumanDecisionRequest,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.asubmit_human_decision(
        workflow_id,
        decision=body.decision,
        feedback=body.feedback,
        actor=body.actor,
        edits=body.edits,
    )


@router.post("/{workflow_id}/rerun", response_model=WorkflowExecutionResponse, status_code=201)
async def rerun_workflow(
    workflow_id: UUID,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.arerun_workflow(workflow_id)


@router.post(
    "/{workflow_id}/tasks/{task_id}/rerun",
    response_model=WorkflowExecutionResponse,
    status_code=201,
)
async def rerun_task(
    workflow_id: UUID,
    task_id: UUID,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.arerun_task(workflow_id, task_id)
