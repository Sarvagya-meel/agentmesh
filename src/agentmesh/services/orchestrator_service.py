from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from agentmesh.core.models import Event, RoutingMode, WorkflowState, WorkflowStatus


@dataclass(frozen=True, slots=True)
class AgentStep:
    """A single task step in the smallest useful multi-agent workflow."""

    name: str
    task_type: str
    agent: str
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_type", str(self.task_type).upper())
        object.__setattr__(self, "agent", str(self.agent).strip())
        object.__setattr__(self, "name", str(self.name).strip())
        if not self.task_type:
            raise ValueError("task_type cannot be empty.")
        if not self.agent:
            raise ValueError("agent cannot be empty.")


class OrchestratorService:
    """Minimal event-driven orchestrator for a small multi-agent workflow."""

    DEFAULT_STEPS = (
        AgentStep("detect_jobs", "JOB_DETECT", "job_detector", "Find matching roles"),
        AgentStep("find_email", "EMAIL_FIND", "email_finder", "Find the contact email"),
        AgentStep("apply", "APPLY", "applicator", "Submit the application"),
    )

    def __init__(self, steps: Iterable[AgentStep] | None = None) -> None:
        self.steps = list(steps or self.DEFAULT_STEPS)

    def start_workflow(
        self,
        conversation_id: str,
        goal: str,
        *,
        workflow_id: UUID | None = None,
        steps: Iterable[AgentStep] | None = None,
    ) -> tuple[WorkflowState, list[Event]]:
        selected_steps = list(steps or self.steps)
        if not selected_steps:
            raise ValueError("At least one agent task is required to start a workflow.")

        resolved_workflow_id = workflow_id or uuid4()
        state = WorkflowState(
            conversation_id=conversation_id,
            workflow_id=resolved_workflow_id,
            status=WorkflowStatus.RUNNING,
            current_step=selected_steps[0].task_type,
            assigned_agents=[step.agent for step in selected_steps],
            pending_event_types=[step.task_type for step in selected_steps],
        )

        events: list[Event] = [
            Event(
                conversation_id=conversation_id,
                workflow_id=resolved_workflow_id,
                event_type="WORKFLOW_STARTED",
                source_agent="orchestrator",
                routing_mode=RoutingMode.DIRECTED,
                target_agent=selected_steps[0].agent,
                payload={"goal": goal, "steps": [step.name for step in selected_steps]},
            )
        ]

        for step in selected_steps:
            events.append(
                Event(
                    conversation_id=conversation_id,
                    workflow_id=resolved_workflow_id,
                    event_type="TASK_ASSIGNED",
                    source_agent="orchestrator",
                    routing_mode=RoutingMode.DIRECTED,
                    target_agent=step.agent,
                    payload={
                        "task_type": step.task_type,
                        "name": step.name,
                        "description": step.description,
                        "goal": goal,
                        **step.payload,
                    },
                )
            )

        return state, events

    def advance_workflow(
        self,
        conversation_id: str,
        workflow_id: UUID,
        *,
        completed_task_type: str,
        completed_agent: str,
        result: dict[str, Any] | None = None,
        steps: Iterable[AgentStep] | None = None,
    ) -> tuple[Event, list[Event]]:
        selected_steps = list(steps or self.steps)
        task_index = next(
            (index for index, step in enumerate(selected_steps) if step.task_type == str(completed_task_type).upper()),
            None,
        )
        if task_index is None:
            raise ValueError(f"Task type {completed_task_type!r} is not part of the workflow plan.")

        completed_event = Event(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            event_type="TASK_COMPLETED",
            source_agent=completed_agent,
            routing_mode=RoutingMode.FANOUT,
            payload={
                "task_type": str(completed_task_type).upper(),
                "result": result or {},
            },
        )

        remaining_steps = selected_steps[task_index + 1 :]
        if not remaining_steps:
            completion_event = Event(
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                event_type="WORKFLOW_COMPLETED",
                source_agent="orchestrator",
                routing_mode=RoutingMode.FANOUT,
                payload={"status": "completed", "result": result or {}},
            )
            return completed_event, [completion_event]

        next_step = remaining_steps[0]
        next_event = Event(
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            event_type="TASK_ASSIGNED",
            source_agent="orchestrator",
            routing_mode=RoutingMode.DIRECTED,
            target_agent=next_step.agent,
            payload={
                "task_type": next_step.task_type,
                "name": next_step.name,
                "description": next_step.description,
                **next_step.payload,
            },
        )
        return completed_event, [next_event]
