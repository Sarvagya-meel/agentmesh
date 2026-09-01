from __future__ import annotations

import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeAlias, cast
from uuid import UUID, uuid4

import httpx
import streamlit as st

from agentmesh.services.service_agentmesh_ui.client import ControlPlaneClient

API_URL = os.getenv("AGENTMESH_API_URL", "http://127.0.0.1:8000")
AGENT_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "90"))
AGENT_STALE_SECONDS = float(os.getenv("AGENT_STALE_SECONDS", "180"))
WORKER_CAPABILITIES = {"ADK", "CHAT", "REVIEW"}
TERMINAL_WORKFLOW_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
JsonObject: TypeAlias = dict[str, Any]

client = ControlPlaneClient(API_URL, timeout_seconds=AGENT_TIMEOUT_SECONDS)


def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "agent_messages": [],
        "pending_direct_input": None,
        "active_queue_id": None,
        "active_orchestration_workflow_id": None,
        "opened_workflow_id": None,
        "activity_runs": {},
        "checkpoint_history": {},
        "checkpoint_replay": {},
        "trace_links": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
        response = client.workflow_activity(
            workflow_id, after_sequence=int(state["cursor"]), limit=100
        )
        return merge_activity(workflow_id, response)
    except (ValueError, httpx.HTTPError) as exc:
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
            trace_state = {**client.trace_link(workflow_id), "checked_at": now}
            st.session_state.trace_links[workflow_id] = trace_state
        except httpx.HTTPError:
            trace_state = {"available": False, "checked_at": now}
    if isinstance(trace_state, dict) and trace_state.get("available") and trace_state.get("url"):
        st.link_button(
            "Open LangSmith trace",
            str(trace_state["url"]),
            icon=":material/open_in_new:",
        )


def event_rows(events: list[JsonObject]) -> list[JsonObject]:
    return [
        {
            "sequence": event.get("sequence_number"),
            "time": event.get("timestamp"),
            "event": event.get("event_type"),
            "source": event.get("source_agent"),
            "destination": event.get("target_agent"),
            "checkpoint": str(
                cast(JsonObject, event.get("metadata", {})).get("checkpoint_id", "")
            ).removeprefix("event:")[:12],
        }
        for event in events
    ]


def render_plan(steps: list[JsonObject]) -> None:
    if not steps:
        st.info("Waiting for the supervisor to publish a plan.")
        return
    st.dataframe(
        [
            {
                "step": int(step.get("position", 0)) + 1,
                "task": step.get("name"),
                "agent": step.get("agent_id"),
                "capability": step.get("required_capability"),
                "status": step.get("status"),
                "dependencies": ", ".join(step.get("dependencies", [])),
            }
            for step in steps
        ],
        width="stretch",
        hide_index=True,
    )


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
            try:
                client.submit_approval(
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
    *,
    workflow_state_key: str,
) -> None:
    with st.expander("Checkpoints, recovery, and reruns"):
        rerun_columns = st.columns(2)
        if rerun_columns[0].button(
            "Rerun workflow",
            key=f"rerun-workflow-{workflow_id}",
            icon=":material/replay:",
            width="stretch",
        ):
            try:
                rerun = client.rerun_workflow(workflow_id)
                rerun_id = str(rerun["workflow_id"])
                reset_activity(rerun_id)
                st.session_state[workflow_state_key] = rerun_id
                st.rerun(scope="app")
            except httpx.HTTPError as exc:
                st.error(str(exc))
        task_options = [step for step in steps if step.get("task_id")]
        selected_task = None
        if task_options:
            selected_task = st.selectbox(
                "Task event to rerun",
                task_options,
                format_func=lambda item: (
                    f"{int(item.get('position', 0)) + 1}. "
                    f"{item.get('name', 'Task')} [{item.get('status', 'PROPOSED')}]"
                ),
                key=f"rerun-task-select-{workflow_id}",
            )
        if rerun_columns[1].button(
            "Rerun task",
            key=f"rerun-task-{workflow_id}",
            disabled=selected_task is None,
            icon=":material/restart_alt:",
            width="stretch",
        ):
            try:
                rerun = client.rerun_task(
                    workflow_id, str(cast(JsonObject, selected_task)["task_id"])
                )
                rerun_id = str(rerun["workflow_id"])
                reset_activity(rerun_id)
                st.session_state[workflow_state_key] = rerun_id
                st.rerun(scope="app")
            except httpx.HTTPError as exc:
                st.error(str(exc))
        if st.button(
            "Load checkpoints",
            key=f"load-checkpoints-{workflow_id}",
            icon=":material/history:",
        ):
            try:
                st.session_state.checkpoint_history[workflow_id] = client.checkpoints(
                    workflow_id
                )
            except httpx.HTTPError as exc:
                st.error(str(exc))
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
        controls = st.columns(2)
        if controls[0].button(
            "Inspect selected",
            key=f"inspect-checkpoint-{workflow_id}",
            disabled=selected_id is None,
            icon=":material/search:",
            width="stretch",
        ):
            try:
                st.session_state.checkpoint_replay[workflow_id] = client.replay_checkpoint(
                    workflow_id, cast(str, selected_id)
                )
            except httpx.HTTPError as exc:
                st.error(str(exc))
        if controls[1].button(
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
                recovery = client.recover_checkpoint(workflow_id, selected_id)
                recovery_id = str(recovery["recovery_workflow_id"])
                reset_activity(recovery_id)
                st.session_state[workflow_state_key] = recovery_id
                st.success(f"Recovery queued as workflow {recovery_id}.")
                st.rerun(scope="app")
            except httpx.HTTPError as exc:
                st.error(str(exc))
        replay = st.session_state.checkpoint_replay.get(workflow_id)
        if replay:
            st.caption("Read-only checkpoint state")
            st.json(replay, expanded=False)


@st.fragment(run_every=1.5)
def render_live_activity(
    workflow_id: str,
    *,
    queued: bool = False,
    workflow_state_key: str = "active_orchestration_workflow_id",
) -> None:
    activity = load_activity(workflow_id)
    state = st.session_state.activity_runs.get(workflow_id, {})
    if activity is None:
        st.info("Waiting for the control plane to publish workflow activity.")
        if state.get("last_error"):
            st.caption("The last refresh failed; polling will retry automatically.")
        return

    workflow = cast(JsonObject, activity.get("workflow", {}))
    status = str(workflow.get("status", "PENDING"))
    heading_columns = st.columns([4, 2])
    heading_columns[0].subheader("Queued run" if queued else "Workflow execution")
    heading_columns[0].caption(f"Workflow ID: {workflow_id}")
    heading_columns[1].metric("Status", status)
    render_trace_link(workflow_id)

    plan_column, event_column = st.columns([1, 1], gap="large")
    with plan_column:
        st.subheader("Proposed plan and progress")
        steps = cast(list[JsonObject], activity.get("steps", []))
        render_plan(steps)
    with event_column:
        st.subheader("Live event flow")
        events = cast(list[JsonObject], activity.get("events", []))
        if events:
            st.dataframe(event_rows(events), width="stretch", hide_index=True, height=320)
        else:
            st.info("Waiting for events.")

    render_interrupt(
        workflow_id,
        cast(JsonObject | None, activity.get("pending_interrupt")),
    )
    if not queued:
        render_checkpoint_controls(
            workflow_id,
            steps,
            workflow_state_key=workflow_state_key,
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


def render_registry() -> None:
    st.title("Registry")
    try:
        resources = client.list_resources()
        audits = client.list_audit_events()
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
    if not mode_is_ready(card, direct=direct):
        st.warning(f"{agent_id} has no ready runtime for this execution mode.")

    for message in st.session_state.agent_messages:
        with st.chat_message(str(message["role"])):
            st.markdown(str(message["content"]))

    pending = st.session_state.pending_direct_input
    if direct and isinstance(pending, dict):
        st.subheader("Action required")
        st.write(str(pending.get("prompt", "Approval is required.")))
        options = normalize_options(pending.get("options"))
        columns = st.columns(len(options))
        for index, option in enumerate(options):
            if columns[index].button(
                option["label"].title(),
                key=f"direct-interrupt-{option['value']}",
                width="stretch",
            ):
                try:
                    result = client.resume_agent(
                        card, str(pending["thread_id"]), option["value"]
                    )
                    st.session_state.agent_messages.append(
                        {"role": "assistant", "content": result_text(result)}
                    )
                    st.session_state.pending_direct_input = None
                    st.rerun()
                except (ValueError, httpx.HTTPError) as exc:
                    st.error(str(exc))

    prompt = st.chat_input(
        "Message agent",
        disabled=bool(pending) or not mode_is_ready(card, direct=direct),
    )
    if prompt:
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        try:
            if direct:
                with st.spinner(f"{agent_id} is processing the direct request..."):
                    result = client.invoke_agent(card, prompt)
                if str(result.get("status", "")).upper() in {
                    "AWAITING_HUMAN",
                    "AWAITING_APPROVAL",
                }:
                    interrupt = result.get("interrupt", {})
                    if not isinstance(interrupt, dict):
                        interrupt = {"prompt": str(interrupt)}
                    st.session_state.pending_direct_input = {
                        **interrupt,
                        "thread_id": result.get("thread_id"),
                    }
                    content = str(interrupt.get("prompt", "Approval is required."))
                else:
                    content = result_text(result)
                st.session_state.agent_messages.append(
                    {"role": "assistant", "content": content}
                )
            else:
                queued = client.submit_assignment(
                    agent_id, prompt, f"playground-{uuid4()}"
                )
                workflow_id = str(queued["workflow_id"])
                reset_activity(workflow_id)
                st.session_state.active_queue_id = workflow_id
            st.rerun()
        except (ValueError, httpx.HTTPError) as exc:
            st.error(str(exc))

    queue_id = st.session_state.active_queue_id
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
            submitted = st.form_submit_button(
                "Start workflow", type="primary", disabled=not goal.strip()
            )
        if submitted:
            try:
                workflow = client.start_workflow(
                    goal.strip(), preferred_agents, f"streamlit-{uuid4()}"
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
st.sidebar.title("AgentMesh")
page = st.sidebar.radio(
    "Navigation",
    ["Registry", "Agent Playground", "Workflow Playground"],
)

try:
    registered_agents = client.list_agents()
except httpx.HTTPError:
    registered_agents = []
worker_cards = worker_agent_cards(registered_agents)

if page == "Registry":
    render_registry()
elif page == "Agent Playground":
    render_agent_playground(worker_cards)
else:
    render_workflow_playground(worker_cards)
