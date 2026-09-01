from __future__ import annotations

from typing import Any

from agentmesh.core.models import Event

TERMINAL_WORKFLOW_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def normalize_pending_interrupt(pending: object) -> dict[str, Any] | None:
    """Expose every supervisor approval through one UI-facing contract."""

    if not isinstance(pending, dict) or not pending:
        return None
    if pending.get("type"):
        return pending
    context = pending.get("context", {})
    context_values = context if isinstance(context, dict) else {}
    options = pending.get("options", [])
    return {
        "type": "human_approval",
        "prompt": str(pending.get("prompt", "Workflow input is required.")),
        "options": [
            {"label": str(option).title(), "value": str(option).upper()}
            for option in options
        ],
        "approval": pending,
        **context_values,
    }


def project_standalone_request(
    workflow: dict[str, Any], events: list[Event]
) -> dict[str, Any]:
    """Project a queued direct request without inventing supervisor activity."""

    assignment = next(
        (
            event
            for event in events
            if event.event_type == "TASK_ASSIGNED"
            and isinstance(event.payload, dict)
            and event.payload.get("standalone") is True
        ),
        None,
    )
    if assignment is None:
        return workflow
    assignment_payload = (
        assignment.payload if isinstance(assignment.payload, dict) else {}
    )
    task = assignment_payload.get("task", {})
    if not isinstance(task, dict):
        task = {}
    terminal = next(
        (
            event
            for event in reversed(events)
            if event.event_type in {"TASK_COMPLETED", "TASK_FAILED"}
        ),
        None,
    )
    status = "RUNNING"
    task_results: list[dict[str, Any]] = []
    task_status = "RUNNING"
    if terminal is not None:
        status = "COMPLETED" if terminal.event_type == "TASK_COMPLETED" else "FAILED"
        task_status = status
        terminal_payload = terminal.payload if isinstance(terminal.payload, dict) else {}
        task_results = [terminal_payload]
    direct_task = {
        **task,
        "name": "Direct agent request",
        "agent_id": assignment.target_agent or "",
        "position": 0,
        "required_capability": "DIRECT",
        "dependencies": [],
        "status": task_status,
    }
    return {
        **workflow,
        "status": status,
        "plan": {
            "goal": str(task.get("description", "")),
            "tasks": [direct_task],
            "planner_provider": "control-plane",
        },
        "current_task": direct_task,
        "pending_input": None,
        "assigned_agents": [assignment.target_agent] if assignment.target_agent else [],
        "task_results": task_results,
    }


def project_step_views(
    workflow: dict[str, Any], events: list[Event]
) -> list[dict[str, Any]]:
    plan = workflow.get("plan") or {}
    raw_tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
    states: dict[str, str] = {}

    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        task = payload.get("task", {})
        nested_task_id = task.get("task_id") if isinstance(task, dict) else ""
        task_id = str(payload.get("task_id") or nested_task_id)
        if not task_id:
            continue
        status = _event_step_status(event.event_type, payload)
        if status:
            states[task_id] = status

    views = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id", ""))
        views.append(
            {
                "task_id": task_id,
                "position": int(task.get("position", 0)),
                "name": str(task.get("name", "Task")),
                "agent_id": str(task.get("agent_id", "")),
                "required_capability": str(task.get("required_capability", "")),
                "dependencies": [str(item) for item in task.get("dependencies", [])],
                "status": states.get(task_id, str(task.get("status", "PROPOSED"))),
            }
        )
    return sorted(views, key=lambda item: item["position"])


def paginate_events(
    events: list[Event], *, after_sequence: int, limit: int
) -> tuple[list[Event], int, bool]:
    ordered = sorted(events, key=lambda event: event.sequence_number or 0)
    remaining = [event for event in ordered if (event.sequence_number or 0) > after_sequence]
    page = remaining[:limit]
    next_sequence = (
        page[-1].sequence_number or after_sequence if page else after_sequence
    )
    return page, next_sequence, len(remaining) > len(page)


def _event_step_status(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "TASK_PROPOSED":
        return "PROPOSED"
    if event_type == "TASK_ASSIGNED":
        return "RUNNING"
    if event_type in {
        "TASK_OUTPUT_RECEIVED",
        "TASK_VALIDATION_REQUESTED",
        "TASK_VALIDATION_COMPLETED",
    }:
        decision = payload.get("decision", {})
        if event_type == "TASK_VALIDATION_COMPLETED" and isinstance(decision, dict):
            return "VALIDATING" if decision.get("valid", False) else "FAILED"
        return "VALIDATING"
    if event_type == "TASK_RERUN_REQUESTED":
        return "RETRYING"
    if event_type == "TASK_COMPLETED":
        return "COMPLETED"
    if event_type == "TASK_FAILED":
        return "FAILED"
    return None
