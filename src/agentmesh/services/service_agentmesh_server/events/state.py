from __future__ import annotations

from uuid import UUID

from agentmesh.core.models import Event, WorkflowState, WorkflowStatus
from agentmesh.core.models.exceptions import WorkflowNotFoundError
from agentmesh.services.service_agentmesh_server.events.service import EventService


class StateService:
    """Project workflow state deterministically from its immutable event history."""

    def __init__(self, event_service: EventService) -> None:
        self.event_service = event_service

    def get_current(self, workflow_id: UUID) -> WorkflowState:
        """Return current state reconstructed from all workflow events."""

        events = self.event_service.replay(workflow_id)
        if not events:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} was not found.")
        return self.project(events)

    @staticmethod
    def project(events: list[Event]) -> WorkflowState:
        """Purely derive state from a sequence-ordered event list."""

        if not events:
            raise WorkflowNotFoundError("Cannot project a workflow without events.")

        ordered_events = sorted(events, key=lambda item: item.sequence_number or 0)
        first = ordered_events[0]
        state = WorkflowState(
            conversation_id=first.conversation_id,
            workflow_id=first.workflow_id,
        )

        for event in ordered_events:
            metadata = dict(state.metadata)
            processed = list(state.processed_event_types)
            assigned_agents = list(state.assigned_agents)
            pending = list(state.pending_event_types)
            status = state.status
            current_step = state.current_step
            payload = event.payload if isinstance(event.payload, dict) else {}

            if event.event_type == "WORKFLOW_STARTED":
                status = WorkflowStatus.RUNNING
                metadata["goal"] = payload.get("goal", "")
            elif event.event_type == "AGENT_SNAPSHOT_CAPTURED":
                metadata["agent_snapshot"] = payload.get("agents", [])
            elif event.event_type == "PLAN_CREATED":
                status = WorkflowStatus.PLANNING
                metadata["plan"] = payload.get("plan", {})
            elif event.event_type == "PLAN_APPROVAL_REQUESTED":
                status = WorkflowStatus.AWAITING_PLAN_APPROVAL
                metadata["pending_approval"] = payload.get("approval", {})
            elif event.event_type == "PLAN_APPROVED":
                status = WorkflowStatus.RUNNING
                metadata.pop("pending_approval", None)
            elif event.event_type in {"PLAN_REJECTED", "WORKFLOW_CANCELLED"}:
                status = WorkflowStatus.CANCELLED
                metadata.pop("pending_approval", None)
            elif event.event_type == "PLAN_REVISION_REQUESTED":
                status = WorkflowStatus.PLANNING
                metadata["revision_feedback"] = payload.get("feedback", "")
                metadata.pop("pending_approval", None)
            elif event.event_type == "TASK_PROPOSED":
                task = payload.get("task", {})
                current_step = task.get("name")
                metadata["current_task"] = task
            elif event.event_type == "TASK_APPROVAL_REQUESTED":
                status = WorkflowStatus.AWAITING_TASK_APPROVAL
                metadata["pending_approval"] = payload.get("approval", {})
            elif event.event_type == "TASK_APPROVED":
                status = WorkflowStatus.RUNNING
                metadata.pop("pending_approval", None)
            elif event.event_type == "TASK_REVISION_REQUESTED":
                status = WorkflowStatus.PLANNING
                metadata["revision_feedback"] = payload.get("feedback", "")
                metadata.pop("pending_approval", None)
            elif event.event_type == "TASK_REJECTED":
                status = WorkflowStatus.CANCELLED
                metadata.pop("pending_approval", None)
            elif event.event_type == "TASK_ASSIGNED":
                status = WorkflowStatus.WAITING_FOR_AGENT
                metadata["assignment_event_id"] = str(event.event_id)
                if event.target_agent and event.target_agent not in assigned_agents:
                    assigned_agents.append(event.target_agent)
                pending = ["TASK_COMPLETED", "TASK_FAILED"]
            elif event.event_type == "TASK_COMPLETED":
                status = WorkflowStatus.RUNNING
                pending = []
                metadata.pop("assignment_event_id", None)
                processed.append(str(payload.get("task_id", event.event_id)))
                results = list(metadata.get("task_results", []))
                results.append(payload)
                metadata["task_results"] = results
            elif event.event_type in {"TASK_FAILED", "WORKFLOW_FAILED"}:
                status = WorkflowStatus.FAILED
                pending = []
                metadata.pop("assignment_event_id", None)
                metadata["failure"] = payload
            elif event.event_type == "WORKFLOW_COMPLETED":
                status = WorkflowStatus.COMPLETED
                pending = []
                current_step = None

            state = WorkflowState(
                conversation_id=state.conversation_id,
                workflow_id=state.workflow_id,
                status=status,
                current_step=current_step,
                assigned_agents=assigned_agents,
                last_event_id=event.event_id,
                processed_event_types=processed,
                pending_event_types=pending,
                metadata=metadata,
            )

        return state
