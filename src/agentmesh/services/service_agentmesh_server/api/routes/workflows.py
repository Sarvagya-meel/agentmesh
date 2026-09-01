from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from agentmesh.config import get_settings
from agentmesh.services.service_agentmesh_server.activity import (
    TERMINAL_WORKFLOW_STATUSES,
    normalize_pending_interrupt,
    paginate_events,
    project_standalone_request,
    project_step_views,
)
from agentmesh.services.service_agentmesh_server.api.dependencies import (
    get_event_service,
    get_master_orchestrator,
)
from agentmesh.services.service_agentmesh_server.api.schemas import (
    CheckpointReplayRequest,
    HumanDecisionRequest,
    LangSmithTraceLinkResponse,
    StartWorkflowRequest,
    WorkflowActivityResponse,
    WorkflowExecutionResponse,
    WorkflowForkRequest,
    WorkflowRecoveryRequest,
    WorkflowRecoveryResponse,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.orchestration import WorkflowOrchestrator
from agentmesh.services.service_agentmesh_server.trace_links import (
    resolve_langsmith_trace_link,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/{workflow_id}/activity", response_model=WorkflowActivityResponse)
def workflow_activity(
    workflow_id: UUID,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
    event_service: Annotated[EventService, Depends(get_event_service)],
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    all_events = event_service.replay(workflow_id)
    workflow = project_standalone_request(
        orchestrator.get_workflow(workflow_id), all_events
    )
    events, next_sequence, has_more = paginate_events(
        all_events, after_sequence=after_sequence, limit=limit
    )
    status = str(workflow.get("status", ""))
    return {
        "workflow": workflow,
        "steps": project_step_views(workflow, all_events),
        "events": events,
        "next_sequence": next_sequence,
        "has_more": has_more,
        "pending_interrupt": normalize_pending_interrupt(workflow.get("pending_input")),
        "terminal": status in TERMINAL_WORKFLOW_STATUSES,
    }


@router.get("/{workflow_id}/trace-link", response_model=LangSmithTraceLinkResponse)
def workflow_trace_link(workflow_id: UUID) -> dict[str, Any]:
    return resolve_langsmith_trace_link(get_settings(), str(workflow_id))


@router.post(
    "/{workflow_id}/recover",
    response_model=WorkflowRecoveryResponse,
    status_code=202,
)
async def recover_workflow_checkpoint(
    workflow_id: UUID,
    body: WorkflowRecoveryRequest,
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_master_orchestrator)],
) -> dict[str, Any]:
    return await orchestrator.arecover_checkpoint(
        workflow_id,
        checkpoint_id=body.checkpoint_id,
        new_workflow_id=body.new_workflow_id,
    )


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
