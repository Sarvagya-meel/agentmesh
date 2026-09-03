from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4, uuid5

import httpx

from agentmesh.core.models import (
    Event,
    HumanDecisionType,
    RoutingMode,
    SupervisorActionType,
    WorkflowStatus,
)
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.supervisor.service import (
    SupervisorActionService,
)


class QueuedWorkflowOrchestrator:
    """Control-plane facade that queues writes for an external supervisor."""

    def __init__(
        self,
        *,
        action_service: SupervisorActionService,
        state_service: StateService,
        supervisor_id: str,
        supervisor_api_url: str,
        service_token: str = "",
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.action_service = action_service
        self.state_service = state_service
        self.supervisor_id = supervisor_id
        self.supervisor_api_url = supervisor_api_url.rstrip("/")
        self.service_token = service_token
        self.request_timeout_seconds = request_timeout_seconds

    def graph_mermaid(self) -> str:
        return (
            "flowchart LR\n"
            "  UI[Streamlit UI] --> CP[Control Plane]\n"
            "  CP --> Q[(Supervisor Action Queue)]\n"
            "  Q --> S[Supervisor]\n"
            "  S --> W[Worker Agents]\n"
            "  W --> CP\n"
        )

    async def astart_workflow(
        self,
        conversation_id: str,
        goal: str,
        *,
        workflow_id: UUID | None = None,
        preferred_agent_ids: list[str] | None = None,
        rerun_of_workflow_id: UUID | None = None,
        rerun_of_task_id: UUID | None = None,
        approval_required: bool = True,
        start_event_persisted: bool = False,
        memory_user_id: str = "",
        memory_opt_in: bool = False,
        memory_updates: dict[str, str] | None = None,
        memory_delete_keys: list[str] | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_workflow_id = workflow_id or uuid4()
        self._ensure_workflow_started(
            resolved_workflow_id,
            conversation_id=conversation_id,
            goal=goal,
            rerun_of_workflow_id=rerun_of_workflow_id,
            rerun_of_task_id=rerun_of_task_id,
            approval_required=approval_required,
        )
        self._enqueue(
            resolved_workflow_id,
            conversation_id=conversation_id,
            action_type=SupervisorActionType.START_WORKFLOW,
            action_key="start",
            arguments={
                "conversation_id": conversation_id,
                "goal": goal,
                "workflow_id": str(resolved_workflow_id),
                "preferred_agent_ids": preferred_agent_ids or [],
                "rerun_of_workflow_id": self._optional_uuid(rerun_of_workflow_id),
                "rerun_of_task_id": self._optional_uuid(rerun_of_task_id),
                "approval_required": approval_required,
                "start_event_persisted": True,
                "memory_user_id": memory_user_id,
                "memory_opt_in": memory_opt_in,
                "memory_updates": memory_updates or {},
                "memory_delete_keys": memory_delete_keys or [],
                "trace_metadata": trace_metadata or {},
            },
        )
        return self.get_workflow(resolved_workflow_id)

    def get_workflow(self, workflow_id: UUID) -> dict[str, Any]:
        state = self.state_service.get_current(workflow_id)
        metadata = state.metadata
        return {
            "workflow_id": str(workflow_id),
            "conversation_id": state.conversation_id,
            "status": str(state.status),
            "plan": metadata.get("plan"),
            "current_task": metadata.get("current_task"),
            "pending_input": metadata.get("pending_approval"),
            "assigned_agents": state.assigned_agents,
            "task_results": metadata.get("task_results", []),
            "rerun_of_workflow_id": metadata.get("rerun_of_workflow_id"),
            "rerun_of_task_id": metadata.get("rerun_of_task_id"),
        }

    async def asubmit_human_decision(
        self,
        workflow_id: UUID,
        *,
        decision: HumanDecisionType | str,
        feedback: str = "",
        actor: str = "human",
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.state_service.get_current(workflow_id)
        if state.status not in {
            WorkflowStatus.AWAITING_PLAN_APPROVAL,
            WorkflowStatus.AWAITING_TASK_APPROVAL,
            WorkflowStatus.AWAITING_AGENT_APPROVAL,
        }:
            return self.get_workflow(workflow_id)
        decision_value = (
            decision.value if isinstance(decision, HumanDecisionType) else str(decision)
        )
        pending = state.metadata.get("pending_approval", {})
        approval_id = pending.get("approval_id") if isinstance(pending, dict) else None
        self._enqueue(
            workflow_id,
            conversation_id=state.conversation_id,
            action_type=SupervisorActionType.HUMAN_DECISION,
            action_key=f"decision:{approval_id or workflow_id}:{decision_value}",
            arguments={
                "workflow_id": str(workflow_id),
                "decision": decision_value,
                "feedback": feedback,
                "actor": actor,
                "edits": edits or {},
            },
        )
        return self.get_workflow(workflow_id)

    async def asubmit_task_result(
        self,
        workflow_id: UUID,
        *,
        task_id: UUID,
        assignment_event_id: UUID,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        state = self.state_service.get_current(workflow_id)
        self._enqueue(
            workflow_id,
            conversation_id=state.conversation_id,
            action_type=SupervisorActionType.TASK_RESULT,
            action_key=f"task-result:{assignment_event_id}",
            arguments={
                "workflow_id": str(workflow_id),
                "task_id": str(task_id),
                "assignment_event_id": str(assignment_event_id),
                "status": status,
                "result": result,
            },
        )
        return self.get_workflow(workflow_id)

    async def arerun_workflow(self, workflow_id: UUID) -> dict[str, Any]:
        state = self.state_service.get_current(workflow_id)
        goal = str(state.metadata.get("goal", "")).strip()
        if not goal:
            raise ValidationError("The original workflow has no goal to rerun.")
        plan = state.metadata.get("plan") or {}
        agents = list(
            dict.fromkeys(
                str(task["agent_id"]) for task in plan.get("tasks", []) if task.get("agent_id")
            )
        )
        return await self._start_rerun(workflow_id, goal, agents)

    async def arerun_task(self, workflow_id: UUID, task_id: UUID) -> dict[str, Any]:
        state = self.state_service.get_current(workflow_id)
        plan = state.metadata.get("plan") or {}
        task = next(
            (item for item in plan.get("tasks", []) if str(item.get("task_id")) == str(task_id)),
            None,
        )
        if task is None:
            raise ValidationError(f"Task {task_id} does not belong to workflow {workflow_id}.")
        return await self._start_rerun(
            workflow_id, str(task["description"]), [str(task["agent_id"])], task_id=task_id
        )

    async def _start_rerun(
        self, source_id: UUID, goal: str, agents: list[str], *, task_id: UUID | None = None
    ) -> dict[str, Any]:
        state = self.state_service.get_current(source_id)
        child_id = uuid4()
        # Allocate durable child identity before returning it to the UI. Planning
        # still runs exclusively through the supervisor's normal start queue.
        result = await self.astart_workflow(
            state.conversation_id,
            goal,
            workflow_id=child_id,
            preferred_agent_ids=agents,
            rerun_of_workflow_id=source_id,
            rerun_of_task_id=task_id,
            approval_required=bool(state.metadata.get("approval_required", True)),
        )
        self.state_service.event_service.append(
            Event(
                conversation_id=state.conversation_id,
                workflow_id=source_id,
                event_type="TASK_RERUN_REQUESTED" if task_id else "WORKFLOW_RERUN_REQUESTED",
                source_agent="agentmesh-control-plane",
                payload={
                    "new_workflow_id": str(child_id),
                    **({"task_id": str(task_id)} if task_id else {}),
                },
            )
        )
        return result

    async def arecover_checkpoint(
        self,
        workflow_id: UUID,
        *,
        checkpoint_id: str | None = None,
        new_workflow_id: UUID | None = None,
        start_event_persisted: bool = False,
    ) -> dict[str, Any]:
        state = self.state_service.get_current(workflow_id)
        if checkpoint_id is not None:
            checkpoint = await self.replay_checkpoint(workflow_id, checkpoint_id)
            if not checkpoint.get("next"):
                raise ValidationError(
                    "The selected checkpoint is terminal and has no executable continuation."
                )
        recovery_workflow_id = new_workflow_id or uuid4()
        self._ensure_workflow_started(
            recovery_workflow_id,
            conversation_id=state.conversation_id,
            goal=str(state.metadata.get("goal", "")),
            rerun_of_workflow_id=workflow_id,
            approval_required=bool(state.metadata.get("approval_required", True)),
        )
        self._enqueue(
            recovery_workflow_id,
            conversation_id=state.conversation_id,
            action_type=SupervisorActionType.RECOVER_CHECKPOINT,
            action_key=f"recover:{workflow_id}:{checkpoint_id or 'latest'}",
            arguments={
                "source_workflow_id": str(workflow_id),
                "checkpoint_id": checkpoint_id,
                "new_workflow_id": str(recovery_workflow_id),
                "start_event_persisted": True,
            },
        )
        return {
            "source_workflow_id": str(workflow_id),
            "recovery_workflow_id": str(recovery_workflow_id),
            "checkpoint_id": checkpoint_id,
            "status": "QUEUED",
        }

    async def checkpoint_history(self, workflow_id: UUID) -> list[dict[str, Any]]:
        response = await self._supervisor_request("GET", f"/workflows/{workflow_id}/checkpoints")
        return list(response.json())

    async def replay_checkpoint(self, workflow_id: UUID, checkpoint_id: str) -> dict[str, Any]:
        response = await self._supervisor_request(
            "POST",
            f"/workflows/{workflow_id}/replay",
            json={"checkpoint_id": checkpoint_id},
        )
        return dict(response.json())

    async def fork_checkpoint(
        self,
        workflow_id: UUID,
        checkpoint_id: str,
        *,
        new_workflow_id: UUID,
        state_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._supervisor_request(
            "POST",
            f"/workflows/{workflow_id}/fork",
            json={
                "checkpoint_id": checkpoint_id,
                "new_workflow_id": str(new_workflow_id),
                "state_updates": state_updates or {},
            },
        )
        return dict(response.json())

    def _enqueue(
        self,
        workflow_id: UUID,
        *,
        conversation_id: str,
        action_type: SupervisorActionType,
        action_key: str,
        arguments: dict[str, Any],
    ) -> None:
        self.action_service.enqueue(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            action_type=action_type,
            arguments=arguments,
            supervisor_id=self.supervisor_id,
            action_event_id=uuid5(workflow_id, action_key),
        )

    def _ensure_workflow_started(
        self,
        workflow_id: UUID,
        *,
        conversation_id: str,
        goal: str,
        rerun_of_workflow_id: UUID | None = None,
        rerun_of_task_id: UUID | None = None,
        approval_required: bool = True,
    ) -> None:
        self.state_service.event_service.append(
            Event(
                event_id=uuid5(workflow_id, "workflow-started"),
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                event_type="WORKFLOW_STARTED",
                source_agent="agentmesh-control-plane",
                routing_mode=RoutingMode.DIRECTED,
                target_agent=self.supervisor_id,
                payload={
                    "goal": goal,
                    "rerun_of_workflow_id": self._optional_uuid(rerun_of_workflow_id),
                    "rerun_of_task_id": self._optional_uuid(rerun_of_task_id),
                    "approval_required": approval_required,
                },
                metadata={"execution_mode": "workflow"},
            )
        )

    async def _supervisor_request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        headers = {"X-AgentMesh-Service-Token": self.service_token} if self.service_token else {}
        async with httpx.AsyncClient(timeout=self.request_timeout_seconds) as client:
            response = await client.request(
                method, f"{self.supervisor_api_url}{path}", json=json, headers=headers
            )
        response.raise_for_status()
        return response

    @staticmethod
    def _optional_uuid(value: UUID | None) -> str | None:
        return str(value) if value is not None else None
