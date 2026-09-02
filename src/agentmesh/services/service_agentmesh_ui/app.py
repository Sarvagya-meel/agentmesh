from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeAlias, cast
from uuid import UUID, uuid4

import httpx
import streamlit as st

from agentmesh.services.service_agentmesh_ui.client import ControlPlaneClient
from agentmesh.services.service_agentmesh_ui.view_models import (
    activity_hash,
    event_label,
    event_route,
    newest_events,
    normalize_registry_url,
)

API_URL = os.getenv("AGENTMESH_API_URL", "http://127.0.0.1:8000")
AGENT_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "90"))
AGENT_STALE_SECONDS = float(os.getenv("AGENT_STALE_SECONDS", "180"))
WORKER_CAPABILITIES = {"ADK", "CHAT", "REVIEW"}
TERMINAL_WORKFLOW_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
JsonObject: TypeAlias = dict[str, Any]

def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "agent_messages_by_scope": {},
        "pending_direct_input_by_scope": {},
        "active_queue_id_by_scope": {},
        "active_orchestration_workflow_id": None,
        "opened_workflow_id": None,
        "activity_runs": {},
        "checkpoint_history": {},
        "checkpoint_replay": {},
        "trace_links": {},
        "registry_url": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def current_client() -> ControlPlaneClient:
    registry_url = st.session_state.registry_url
    if not registry_url:
        raise RuntimeError("Connect to a registry before using AgentMesh.")
    return ControlPlaneClient(
        str(registry_url), timeout_seconds=AGENT_TIMEOUT_SECONDS
    )


def reset_registry_bound_state() -> None:
    st.session_state.agent_messages_by_scope.clear()
    st.session_state.pending_direct_input_by_scope.clear()
    st.session_state.active_queue_id_by_scope.clear()
    st.session_state.active_orchestration_workflow_id = None
    st.session_state.opened_workflow_id = None
    st.session_state.activity_runs.clear()
    st.session_state.checkpoint_history.clear()
    st.session_state.checkpoint_replay.clear()
    st.session_state.trace_links.clear()


def agent_is_recent(last_seen: Any) -> bool:
    if not last_seen:
        return False
    try:
        seen_at = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    except ValueError:
        return False
    if seen_at.tzinfo is None:
        seen_at = seen_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - seen_at <= timedelta(seconds=AGENT_STALE_SECONDS)


def worker_agent_cards(cards: list[JsonObject]) -> list[JsonObject]:
    workers = []
    for card in cards:
        capabilities = {str(value).upper() for value in card.get("capabilities", [])}
        metadata = card.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        if (
            card.get("status") == "online"
            and capabilities & WORKER_CAPABILITIES
            and agent_is_recent(card.get("last_seen"))
            and (metadata.get("direct_ready", True) or metadata.get("assignment_ready", True))
        ):
            workers.append(card)
    return workers


def mode_is_ready(card: JsonObject, *, direct: bool) -> bool:
    metadata = card.get("metadata", {})
    if not isinstance(metadata, dict):
        return True
    return bool(metadata.get("direct_ready" if direct else "assignment_ready", True))


def normalize_options(options: Sequence[Any] | None) -> list[dict[str, str]]:
    normalized = []
    for option in options or ["approve", "reject"]:
        if isinstance(option, dict):
            value = str(option.get("value", option.get("label", "")))
            label = str(option.get("label", value))
        else:
            value = str(option)
            label = value
        if value:
            normalized.append({"label": label, "value": value})
    return normalized


def result_text(result: JsonObject) -> str:
    return str(
        result.get("final_reply")
        or result.get("draft_reply")
        or result.get("answer")
        or "The agent returned no text response."
    )


def workflow_answer(workflow: JsonObject) -> str | None:
    for task_result in reversed(workflow.get("task_results", [])):
        if not isinstance(task_result, dict):
            continue
        result = task_result.get("result", {})
        if not isinstance(result, dict):
            continue
        answer = result.get("final_reply") or result.get("answer") or result.get("draft_reply")
        if answer:
            return str(answer)
    return None


def reset_activity(workflow_id: str) -> None:
    st.session_state.activity_runs.pop(workflow_id, None)
    st.session_state.trace_links.pop(workflow_id, None)
    st.session_state.checkpoint_history.pop(workflow_id, None)
    st.session_state.checkpoint_replay.pop(workflow_id, None)


def agent_playground_scope(agent_id: str, mode: str) -> str:
    return f"{agent_id}:{mode}"


def merge_activity(workflow_id: str, response: JsonObject) -> JsonObject:
    state = st.session_state.activity_runs.setdefault(
        workflow_id,
        {"cursor": 0, "events": [], "snapshot": None, "last_error": None},
    )
    events_by_id = {
        str(event.get("event_id")): event
        for event in state["events"]
        if isinstance(event, dict)
    }
    for event in response.get("events", []):
        if isinstance(event, dict):
            events_by_id[str(event.get("event_id"))] = event
    state["events"] = sorted(
        events_by_id.values(), key=lambda item: int(item.get("sequence_number") or 0)
    )
    state["cursor"] = int(response.get("next_sequence") or state["cursor"])
    state["snapshot"] = {**response, "events": state["events"]}
    state["last_error"] = None
    return cast(JsonObject, state["snapshot"])


def load_activity(workflow_id: str) -> JsonObject | None:
    state = st.session_state.activity_runs.setdefault(
        workflow_id,
        {"cursor": 0, "events": [], "snapshot": None, "last_error": None},
    )
    snapshot = state.get("snapshot")
    if isinstance(snapshot, dict) and snapshot.get("terminal"):
        return cast(JsonObject, snapshot)
    try:
        response = current_client().workflow_activity(
            workflow_id, after_sequence=int(state["cursor"]), limit=100
        )
        return merge_activity(workflow_id, response)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        state["last_error"] = str(exc)
        return cast(JsonObject | None, snapshot)


def render_trace_link(workflow_id: str) -> None:
    trace_state = st.session_state.trace_links.get(workflow_id)
    now = time.monotonic()
    should_refresh = not isinstance(trace_state, dict) or (
        not trace_state.get("available")
        and now - float(trace_state.get("checked_at", 0)) >= 8
    )
    if should_refresh:
        try:
            trace_state = {**current_client().trace_link(workflow_id), "checked_at": now}
            st.session_state.trace_links[workflow_id] = trace_state
        except httpx.HTTPError:
            trace_state = {"available": False, "checked_at": now}
    if isinstance(trace_state, dict) and trace_state.get("available") and trace_state.get("url"):
        st.link_button(
            "Open LangSmith trace",
            str(trace_state["url"]),
            icon=":material/open_in_new:",
        )


def render_shell_styles() -> None:
    st.html(
        """
        <style>
        div[class*="st-key-main-page-navigation"] [data-testid="stSegmentedControl"] {
            justify-content: flex-end;
        }
        div[class*="st-key-main-page-navigation"] [data-testid="stSegmentedControl"] > div {
            width: 100%;
        }
        div[class*="st-key-event-trail-item-"] {
            border-left: 2px solid #64748b;
            margin-left: 0.45rem;
            padding: 0.15rem 0 0.85rem 1rem;
            position: relative;
        }
        div[class*="st-key-event-trail-item-"]::before {
            background: #2563eb;
            border: 3px solid Canvas;
            border-radius: 50%;
            content: "";
            height: 0.75rem;
            left: -0.45rem;
            position: absolute;
            top: 0.55rem;
            width: 0.75rem;
        }
        div[class*="st-key-event-trail-item-"] p {
            line-height: 1.25;
            overflow-wrap: anywhere;
        }
        @media (max-width: 900px) {
            div[class*="st-key-main-page-navigation"] [data-testid="stSegmentedControl"] {
                justify-content: flex-start;
            }
        }
        </style>
        """
    )


def render_top_navigation() -> str:
    brand_column, navigation_column = st.columns(
        [1, 4], vertical_alignment="center", gap="medium"
    )
    brand_column.markdown("### AgentMesh")
    page = navigation_column.segmented_control(
        "Page navigation",
        ["Registry", "Agent Playground", "Workflow Playground"],
        default="Registry",
        key="main-page-navigation",
        label_visibility="collapsed",
        width="stretch",
    )
    st.divider()
    return str(page or "Registry")


def render_event_trail(workflow_id: str, events: list[JsonObject]) -> None:
    if not events:
        st.info("Waiting for events.")
        return
    st.caption("Latest event first")
    for event in newest_events(events):
        event_object = cast(JsonObject, event)
        event_key = str(event_object.get("event_id") or event_object.get("sequence_number"))
        with st.container(key=f"event-trail-item-{workflow_id}-{event_key}"):
            route_column, event_column, view_column = st.columns(
                [1.1, 1.2, 1.4], vertical_alignment="center", gap="small"
            )
            route_column.caption(event_route(event_object))
            sequence_number = event_object.get("sequence_number", "-")
            event_column.markdown(
                f"**{sequence_number}. {event_label(event_object)}**"
            )
            with view_column.popover(
                "View",
                icon=":material/visibility:",
                help="View the complete raw event record",
                width="content",
            ):
                st.caption(
                    f"Raw event {event_object.get('event_id', '')} - "
                    f"sequence {event_object.get('sequence_number', '-')}"
                )
                st.code(
                    json.dumps(event_object, indent=2, default=str),
                    language="json",
                    wrap_lines=True,
                )


def render_plan(
    steps: list[JsonObject], workflow: JsonObject, events: list[JsonObject]
) -> None:
    if not steps:
        st.info("Waiting for the supervisor to publish a plan.")
        return
    plan = workflow.get("plan", {})
    plan = plan if isinstance(plan, dict) else {}
    planned_tasks = {
        str(task.get("task_id")): task
        for task in plan.get("tasks", [])
        if isinstance(task, dict) and task.get("task_id")
    }
    task_results = {
        str(result.get("task_id")): result
        for result in workflow.get("task_results", [])
        if isinstance(result, dict) and result.get("task_id")
    }
    assigned_tasks: dict[str, JsonObject] = {}
    for event in events:
        if event.get("event_type") != "TASK_ASSIGNED":
            continue
        event_payload = event.get("payload", {})
        if not isinstance(event_payload, dict):
            continue
        assigned_task = event_payload.get("task", {})
        if isinstance(assigned_task, dict) and assigned_task.get("task_id"):
            assigned_tasks[str(assigned_task["task_id"])] = assigned_task
    ordered_steps = sorted(steps, key=lambda item: int(item.get("position", 0)))
    main_goal = str(plan.get("goal") or "Not specified")
    st.markdown(f"**GOAL:** {main_goal}")
    step_labels: dict[str, str] = {}
    for step in ordered_steps:
        label_task_id = str(step.get("task_id") or "")
        if not label_task_id:
            continue
        label_task = planned_tasks.get(label_task_id, {})
        label_name = str(label_task.get("name") or step.get("name") or "Task")
        step_labels[label_task_id] = f"{int(step.get('position', 0))}: {label_name}"
    for step in ordered_steps:
        step_number = int(step.get("position", 0)) + 1
        step_key = str(step.get("task_id") or step_number)
        planned_task = cast(JsonObject, planned_tasks.get(step_key, {}))
        dispatched_task = assigned_tasks.get(step_key, planned_task)
        task_result = cast(JsonObject, task_results.get(step_key, {}))
        task_payload = dispatched_task.get("payload", {})
        if not isinstance(task_payload, dict):
            task_payload = {}
        workflow_context = task_payload.get("workflow_context", {})
        if not isinstance(workflow_context, dict):
            workflow_context = {}
        resolved_inputs = workflow_context.get("resolved_inputs", {})
        if not isinstance(resolved_inputs, dict):
            resolved_inputs = {}
        step_name = str(planned_task.get("name") or step.get("name") or "Task")
        agent_name = str(
            step.get("agent_id") or planned_task.get("agent_id") or "Unassigned"
        )
        capability = str(
            step.get("required_capability")
            or planned_task.get("required_capability")
            or "Not specified"
        )
        agent_goal = str(task_payload.get("goal") or "Not specified")
        goal_description = str(planned_task.get("description") or "Not specified")
        expected_goal = str(planned_task.get("expected_output") or "Not specified")
        raw_dependencies = planned_task.get(
            "dependencies", step.get("dependencies", [])
        )
        dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
        dependency_labels = [
            step_labels.get(str(dependency), f"Unknown task: {dependency}")
            for dependency in dependencies
        ]
        dependency_text = ", ".join(dependency_labels) or "None"
        with st.container(key=f"plan-step-{step_key}"):
            title_column, input_column, output_column = st.columns([2.6, 1.8, 1.9])
            title_column.markdown(f"**{step_number}.) {step_name}**")
            with input_column.popover(
                "View input",
                help="View the complete input for this step",
                width="stretch",
            ):
                st.markdown("**Resolved dependency context**")
                if resolved_inputs:
                    st.json(resolved_inputs, expanded=True)
                else:
                    st.caption("This step has no dependency output.")
                st.markdown("**Full dispatched task**")
                st.json(
                    {
                        "step": step,
                        "planned_task": planned_task,
                        "dispatched_task": dispatched_task,
                    },
                    expanded=2,
                )
            with output_column.popover(
                "View output",
                help="View the complete output for this step",
                width="stretch",
            ):
                if task_result:
                    st.json(task_result, expanded=2)
                else:
                    st.info("No output has been published yet.")
            st.markdown(f"**Agent Name:** {agent_name}")
            st.markdown(f"**Agent Capability:** {capability}")
            st.markdown(f"**Agent Goal:** {agent_goal}")
            st.markdown(f"**Agent Goal Description:** {goal_description}")
            st.markdown(f"**Agent Goal Expected:** {expected_goal}")
            st.markdown(f"**Agent Dependency:** {dependency_text}")
            st.divider()


def render_interrupt(workflow_id: str, pending: JsonObject | None) -> None:
    if not pending:
        return
    st.subheader("Action required")
    st.write(str(pending.get("prompt", "Workflow input is required.")))
    draft = pending.get("draft_reply")
    if draft:
        st.info(str(draft))
    interrupt_type = str(pending.get("type", "human_approval"))
    if interrupt_type != "human_approval":
        st.warning(f"Unsupported interrupt type: {interrupt_type}")
        return
    approval = pending.get("approval", {})
    approval_id = str(approval.get("approval_id", workflow_id))
    feedback = st.text_area(
        "Feedback",
        key=f"interrupt-feedback-{approval_id}",
        placeholder="Required when requesting a revision",
    )
    options = normalize_options(pending.get("options"))
    columns = st.columns(len(options))
    for index, option in enumerate(options):
        if columns[index].button(
            option["label"].title(),
            key=f"interrupt-{approval_id}-{option['value']}",
            width="stretch",
        ):
            if option["value"].lower() == "revise" and not feedback.strip():
                st.error("Add revision instructions before revising.")
                continue
            try:
                current_client().submit_approval(
                    workflow_id, option["value"], feedback=feedback.strip()
                )
                state = st.session_state.activity_runs.get(workflow_id, {})
                if isinstance(state, dict):
                    state["snapshot"] = None
                st.rerun(scope="app")
            except httpx.HTTPError as exc:
                st.error(str(exc))


def render_checkpoint_controls(
    workflow_id: str,
    steps: list[JsonObject],
    workflow: JsonObject,
    *,
    workflow_state_key: str,
    enabled: bool = True,
) -> None:
    st.subheader("Checkpoints and recovery")
    if not enabled:
        st.info("Supervisor checkpoint controls are available for orchestrated workflows.")
        return
    st.caption(f"Current workflow ID: {workflow_id}")
    parent_workflow_id = workflow.get("rerun_of_workflow_id")
    parent_task_id = workflow.get("rerun_of_task_id")
    if parent_workflow_id:
        st.caption(f"Parent workflow ID: {parent_workflow_id}")
    if parent_task_id:
        st.caption(f"Parent task ID: {parent_task_id}")

    if st.button(
        "Rerun workflow",
        key=f"rerun-workflow-{workflow_id}",
        icon=":material/replay:",
        width="stretch",
    ):
        try:
            rerun = current_client().rerun_workflow(workflow_id)
            rerun_id = str(rerun["workflow_id"])
            reset_activity(rerun_id)
            st.session_state[workflow_state_key] = rerun_id
            st.rerun(scope="app")
        except httpx.HTTPError as exc:
            st.error(str(exc))
    st.caption(
        "Starts a fresh workflow from the original goal and selected agents. "
        "Planning begins again; the source workflow remains unchanged."
    )
    st.divider()

    task_options = [step for step in steps if step.get("task_id")]
    selected_task = None
    if task_options:
        selected_task = st.selectbox(
            "Task to rerun",
            task_options,
            format_func=lambda item: (
                f"{int(item.get('position', 0)) + 1}. "
                f"{item.get('name', 'Task')} [{item.get('status', 'PROPOSED')}]"
            ),
            key=f"rerun-task-select-{workflow_id}",
        )
    if st.button(
        "Rerun task",
        key=f"rerun-task-{workflow_id}",
        disabled=selected_task is None,
        icon=":material/restart_alt:",
        width="stretch",
    ):
        try:
            rerun = current_client().rerun_task(
                workflow_id, str(cast(JsonObject, selected_task)["task_id"])
            )
            rerun_id = str(rerun["workflow_id"])
            reset_activity(rerun_id)
            st.session_state[workflow_state_key] = rerun_id
            st.rerun(scope="app")
        except httpx.HTTPError as exc:
            st.error(str(exc))
    st.caption(
        "Creates a fresh workflow for the selected task description, preferring its "
        "original agent. The new run records both the parent workflow and task IDs."
    )
    st.divider()

    if st.button(
        "Load checkpoints",
        key=f"load-checkpoints-{workflow_id}",
        icon=":material/history:",
        width="stretch",
    ):
        try:
            st.session_state.checkpoint_history[workflow_id] = current_client().checkpoints(
                workflow_id
            )
        except httpx.HTTPError as exc:
            st.error(str(exc))
    st.caption(
        "Loads the supervisor's durable LangGraph continuation points for this workflow "
        "thread. A checkpoint with no next node is terminal."
    )

    history = st.session_state.checkpoint_history.get(workflow_id, [])
    checkpoints = [
        item
        for item in history
        if isinstance(item, dict) and item.get("checkpoint_id")
    ]
    selected_id: str | None = None
    selected_recoverable = not checkpoints
    if checkpoints:
        selected = st.selectbox(
            "Checkpoint",
            checkpoints,
            format_func=lambda item: (
                f"{str(item.get('created_at', ''))[:19]}  "
                f"{str(item.get('checkpoint_id'))[:12]}  "
                f"next: {', '.join(item.get('next', [])) or 'terminal'}"
            ),
            key=f"checkpoint-select-{workflow_id}",
        )
        selected_id = str(selected["checkpoint_id"])
        selected_recoverable = bool(selected.get("next"))
    if st.button(
        "Investigate checkpoint",
        key=f"inspect-checkpoint-{workflow_id}",
        disabled=selected_id is None,
        icon=":material/search:",
        width="stretch",
    ):
        try:
            st.session_state.checkpoint_replay[workflow_id] = (
                current_client().replay_checkpoint(workflow_id, cast(str, selected_id))
            )
        except httpx.HTTPError as exc:
            st.error(str(exc))
    st.caption(
        "Performs read-only replay of the selected graph state. It does not execute "
        "agents, append events, dispatch workers, or repeat external side effects."
    )

    if st.button(
        "Recover selected" if checkpoints else "Recover latest",
        key=f"recover-checkpoint-{workflow_id}",
        disabled=not selected_recoverable,
        help=(
            "Recovery creates a new workflow and preserves source history."
            if selected_recoverable
            else "This checkpoint is terminal; choose one with a next step."
        ),
        icon=":material/restart_alt:",
        width="stretch",
    ):
        try:
            recovery = current_client().recover_checkpoint(workflow_id, selected_id)
            recovery_id = str(recovery["recovery_workflow_id"])
            reset_activity(recovery_id)
            st.session_state[workflow_state_key] = recovery_id
            st.success(f"Recovery queued as workflow {recovery_id}.")
            st.rerun(scope="app")
        except httpx.HTTPError as exc:
            st.error(str(exc))
    st.caption(
        "Continues a non-terminal checkpoint in a new immutable workflow history. "
        "Completed results are copied and the source workflow remains unchanged."
    )

    replay = st.session_state.checkpoint_replay.get(workflow_id)
    if replay:
        st.markdown("**Read-only checkpoint state**")
        st.json(replay, expanded=False)


def render_activity_content(
    workflow_id: str,
    activity: JsonObject,
    *,
    queued: bool = False,
    workflow_state_key: str = "active_orchestration_workflow_id",
) -> None:
    workflow = cast(JsonObject, activity.get("workflow", {}))
    status = str(workflow.get("status", "PENDING"))
    heading_columns = st.columns([4, 2])
    heading_columns[0].subheader("Queued run" if queued else "Workflow execution")
    heading_columns[0].caption(f"Workflow ID: {workflow_id}")
    heading_columns[1].metric("Status", status)
    render_trace_link(workflow_id)

    steps = cast(list[JsonObject], activity.get("steps", []))
    events = cast(list[JsonObject], activity.get("events", []))
    plan = workflow.get("plan") if isinstance(workflow, dict) else {}
    supervised_workflow = not (
        isinstance(plan, dict) and plan.get("planner_provider") == "control-plane"
    )

    recovery_column, workspace_column, event_column = st.columns(
        [1, 1, 1], gap="medium"
    )
    with recovery_column:
        if queued:
            st.subheader("Run controls")
            st.info("Checkpoint recovery is available for orchestrated workflows.")
        else:
            render_checkpoint_controls(
                workflow_id,
                steps,
                workflow,
                workflow_state_key=workflow_state_key,
                enabled=supervised_workflow,
            )
    with workspace_column:
        st.subheader("Proposed plan and progress")
        render_plan(steps, workflow, events)
        render_interrupt(
            workflow_id,
            cast(JsonObject | None, activity.get("pending_interrupt")),
        )
        if status in TERMINAL_WORKFLOW_STATUSES:
            answer = workflow_answer(workflow)
            st.subheader("Result")
            if answer:
                st.markdown(answer)
            elif status == "COMPLETED":
                st.info("Workflow completed without a text result.")
            else:
                st.error(f"Workflow ended with status {status}.")
    with event_column:
        st.subheader("Live event trail")
        render_event_trail(workflow_id, events)


def activity_is_terminal(activity: JsonObject) -> bool:
    workflow = activity.get("workflow", {})
    status = str(workflow.get("status", "")) if isinstance(workflow, dict) else ""
    return bool(activity.get("terminal")) or status in TERMINAL_WORKFLOW_STATUSES


@st.fragment(run_every=2.0, parallel=True)
def monitor_activity(workflow_id: str) -> None:
    initialize_state()
    activity = load_activity(workflow_id)
    state = st.session_state.activity_runs.get(workflow_id, {})
    if activity is None:
        return
    digest = activity_hash(activity)
    if state.get("rendered_hash") != digest:
        state["rendered_hash"] = digest
        st.rerun(scope="app")


def render_live_activity(
    workflow_id: str,
    *,
    queued: bool = False,
    workflow_state_key: str = "active_orchestration_workflow_id",
) -> None:
    initialize_state()
    state = st.session_state.activity_runs.get(workflow_id, {})
    snapshot = state.get("snapshot") if isinstance(state, dict) else None
    if isinstance(snapshot, dict):
        render_activity_content(
            workflow_id,
            cast(JsonObject, snapshot),
            queued=queued,
            workflow_state_key=workflow_state_key,
        )
        if not activity_is_terminal(snapshot):
            monitor_activity(workflow_id)
        return
    st.info("Waiting for the control plane to publish workflow activity.")
    if state.get("last_error"):
        st.caption("The last refresh failed; the monitor will retry automatically.")
    monitor_activity(workflow_id)


def render_registry() -> None:
    st.title("Registry")
    connected_url = st.session_state.registry_url
    requested_default = str(connected_url or API_URL)
    with st.form("registry-connection"):
        requested_url = st.text_input(
            "Registry URL",
            value=requested_default,
            placeholder="http://localhost:8000",
        )
        connection_columns = st.columns(2)
        connect_submitted = connection_columns[0].form_submit_button(
            "Connect",
            type="primary",
            icon=":material/link:",
            width="stretch",
        )
        disconnect_submitted = connection_columns[1].form_submit_button(
            "Disconnect",
            icon=":material/link_off:",
            disabled=not bool(connected_url),
            width="stretch",
        )
    if disconnect_submitted:
        st.session_state.registry_url = None
        reset_registry_bound_state()
        st.rerun()
    if connect_submitted:
        try:
            normalized_url = normalize_registry_url(requested_url)
            health = ControlPlaneClient(
                normalized_url, timeout_seconds=AGENT_TIMEOUT_SECONDS
            ).health()
            if str(health.get("status", "")).lower() not in {"ok", "ready", "healthy"}:
                raise ValueError("Registry health endpoint did not report a ready status.")
            if normalized_url != connected_url:
                st.session_state.registry_url = normalized_url
                reset_registry_bound_state()
            st.rerun()
        except (ValueError, httpx.HTTPError) as exc:
            st.error(f"Could not connect to registry: {exc}")
            return
    if not connected_url:
        st.info("Registry is not connected.")
        return
    st.caption(f"Connected registry: {connected_url}")
    try:
        api = current_client()
        resources = api.list_resources()
        audits = api.list_audit_events()
    except httpx.HTTPError as exc:
        st.error(f"Registry API unavailable: {exc}")
        return
    metrics = st.columns(3)
    metrics[0].metric("Resources", len(resources))
    metrics[1].metric("Online", sum(row.get("status") == "online" for row in resources))
    metrics[2].metric("Stale", sum(row.get("status") == "stale" for row in resources))
    if st.button("Refresh", icon=":material/refresh:"):
        st.rerun()
    st.subheader("Resources")
    st.dataframe(resources, width="stretch", hide_index=True)
    st.subheader("Audit trail")
    st.dataframe(audits, width="stretch", hide_index=True)


def render_agent_playground(worker_cards: list[JsonObject]) -> None:
    st.title("Agent Playground")
    if not worker_cards:
        st.warning("No online worker agents are registered.")
        return
    cards_by_id = {str(card["agent_id"]): card for card in worker_cards}
    agent_id = str(st.selectbox("Agent", options=list(cards_by_id)))
    card = cards_by_id[agent_id]
    mode = str(
        st.segmented_control(
            "Execution",
            options=["Direct API Request", "Control Plane Request"],
            default="Direct API Request",
        )
        or "Direct API Request"
    )
    direct = mode == "Direct API Request"
    scope = agent_playground_scope(agent_id, mode)
    metadata = card.get("metadata", {})
    supports_approval = isinstance(metadata, dict) and bool(
        metadata.get("approval_modes")
    )
    approval_required = False
    if supports_approval:
        approval_required = st.toggle(
            "Require human approval",
            value=True,
            key=f"agent-approval-required-{scope}",
        )
    messages_by_scope = st.session_state.agent_messages_by_scope
    pending_by_scope = st.session_state.pending_direct_input_by_scope
    queue_by_scope = st.session_state.active_queue_id_by_scope
    messages = messages_by_scope.setdefault(scope, [])
    if not mode_is_ready(card, direct=direct):
        st.warning(f"{agent_id} has no ready runtime for this execution mode.")

    for message in messages:
        with st.chat_message(str(message["role"])):
            st.markdown(str(message["content"]))

    pending = pending_by_scope.get(scope)
    if direct and isinstance(pending, dict):
        st.subheader("Action required")
        st.write(str(pending.get("prompt", "Approval is required.")))
        draft_reply = pending.get("draft_reply")
        if draft_reply:
            st.info(str(draft_reply))
        feedback = st.text_area(
            "Feedback",
            key=f"direct-interrupt-feedback-{scope}-{pending.get('thread_id', '')}",
            placeholder="Required when requesting a revision",
        )
        options = normalize_options(pending.get("options"))
        columns = st.columns(len(options))
        for index, option in enumerate(options):
            if columns[index].button(
                option["label"].title(),
                key=f"direct-interrupt-{scope}-{option['value']}",
                width="stretch",
            ):
                if option["value"].lower() == "revise" and not feedback.strip():
                    st.error("Add revision instructions before revising.")
                    continue
                try:
                    result = current_client().resume_agent(
                        card,
                        str(pending["thread_id"]),
                        option["value"],
                        feedback=feedback.strip(),
                    )
                    if str(result.get("status", "")).upper() in {
                        "AWAITING_HUMAN",
                        "AWAITING_APPROVAL",
                    }:
                        interrupt = result.get("interrupt", {})
                        if not isinstance(interrupt, dict):
                            interrupt = {"prompt": str(interrupt)}
                        pending_by_scope[scope] = {
                            **interrupt,
                            "thread_id": result.get("thread_id", pending["thread_id"]),
                        }
                        content = str(
                            interrupt.get("prompt", "Approval is required.")
                        )
                    else:
                        pending_by_scope.pop(scope, None)
                        content = result_text(result)
                    messages.append({"role": "assistant", "content": content})
                    st.rerun()
                except (ValueError, httpx.HTTPError) as exc:
                    st.error(str(exc))

    prompt = st.chat_input(
        "Message agent",
        disabled=bool(pending) or not mode_is_ready(card, direct=direct),
    )
    if prompt:
        messages.append({"role": "user", "content": prompt})
        try:
            if direct:
                with st.spinner(f"{agent_id} is processing the direct request..."):
                    result = current_client().invoke_agent(
                        card, prompt, approval_required=approval_required
                    )
                if str(result.get("status", "")).upper() in {
                    "AWAITING_HUMAN",
                    "AWAITING_APPROVAL",
                }:
                    interrupt = result.get("interrupt", {})
                    if not isinstance(interrupt, dict):
                        interrupt = {"prompt": str(interrupt)}
                    pending_by_scope[scope] = {
                        **interrupt,
                        "thread_id": result.get("thread_id"),
                    }
                    content = str(interrupt.get("prompt", "Approval is required."))
                else:
                    content = result_text(result)
                messages.append({"role": "assistant", "content": content})
            else:
                queued = current_client().submit_assignment(
                    agent_id,
                    prompt,
                    f"playground-{uuid4()}",
                    approval_required=approval_required,
                )
                workflow_id = str(queued["workflow_id"])
                reset_activity(workflow_id)
                queue_by_scope[scope] = workflow_id
            st.rerun()
        except (ValueError, httpx.HTTPError) as exc:
            st.error(str(exc))

    queue_id = queue_by_scope.get(scope)
    if not direct and queue_id:
        render_live_activity(str(queue_id), queued=True)


def render_workflow_playground(worker_cards: list[JsonObject]) -> None:
    st.title("Workflow Playground")
    worker_ids = [str(card["agent_id"]) for card in worker_cards]
    orchestration_tab, existing_tab = st.tabs(
        ["Orchestration", "Open existing"],
        key="workflow_playground_tab",
    )

    with orchestration_tab:
        with st.form("start-workflow"):
            goal = st.text_area(
                "Workflow goal",
                placeholder="Describe the result the supervisor should plan and deliver",
            )
            preferred_agents = cast(
                list[str], st.multiselect("Preferred agents", options=worker_ids)
            )
            approval_required = st.toggle(
                "Require human approval",
                value=True,
                key="workflow-approval-required",
            )
            submitted = st.form_submit_button("Start workflow", type="primary")
        if submitted:
            if not goal.strip():
                st.error("Enter a workflow goal before starting.")
                return
            try:
                workflow = current_client().start_workflow(
                    goal.strip(),
                    preferred_agents,
                    f"streamlit-{uuid4()}",
                    approval_required=approval_required,
                )
                workflow_id = str(workflow["workflow_id"])
                reset_activity(workflow_id)
                st.session_state.active_orchestration_workflow_id = workflow_id
                st.rerun()
            except httpx.HTTPError as exc:
                st.error(str(exc))

        orchestration_id = st.session_state.active_orchestration_workflow_id
        if orchestration_id:
            render_live_activity(
                str(orchestration_id),
                workflow_state_key="active_orchestration_workflow_id",
            )

    with existing_tab:
        with st.form("open-existing-workflow"):
            requested_id = st.text_input(
                "Workflow ID",
                value=str(st.session_state.opened_workflow_id or ""),
                placeholder="UUID",
            )
            open_submitted = st.form_submit_button(
                "Open workflow",
                icon=":material/folder_open:",
            )
        if open_submitted:
            try:
                workflow_id = str(UUID(requested_id.strip()))
                reset_activity(workflow_id)
                st.session_state.opened_workflow_id = workflow_id
                st.rerun()
            except ValueError:
                st.error("Enter a valid workflow UUID.")

        opened_id = st.session_state.opened_workflow_id
        if opened_id:
            render_live_activity(
                str(opened_id),
                workflow_state_key="opened_workflow_id",
            )


st.set_page_config(page_title="AgentMesh", layout="wide")
initialize_state()
render_shell_styles()
page = render_top_navigation()

if page == "Registry":
    render_registry()
else:
    if not st.session_state.registry_url:
        st.warning("Connect to a registry from the Registry page first.")
        st.stop()
    try:
        registered_agents = current_client().list_agents()
    except httpx.HTTPError:
        registered_agents = []
    worker_cards = worker_agent_cards(registered_agents)
    if page == "Agent Playground":
        render_agent_playground(worker_cards)
    else:
        render_workflow_playground(worker_cards)
