from __future__ import annotations

import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeAlias, cast
from uuid import uuid4

import httpx
import psycopg
import streamlit as st
from psycopg.rows import dict_row

API_URL = os.getenv("AGENTMESH_API_URL", "http://127.0.0.1:8000")
REGISTRY_URL = os.getenv(
    "AGENT_REGISTRY_URL",
    "http://127.0.0.1:8000/registry/agents",
)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh",
)
AGENT_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "90"))
AGENT_STALE_SECONDS = float(os.getenv("AGENT_STALE_SECONDS", "180"))
WORKER_CAPABILITIES = {"ADK", "CHAT", "REVIEW"}
TERMINAL_WORKFLOW_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
JsonObject: TypeAlias = dict[str, Any]


def fetch_registered_agents() -> list[JsonObject]:
    try:
        response = httpx.get(REGISTRY_URL, timeout=5.0)
        response.raise_for_status()
        return cast(list[JsonObject], response.json())
    except httpx.HTTPError:
        return []


def worker_agent_cards(cards: list[JsonObject]) -> list[JsonObject]:
    workers = []
    for card in cards:
        capabilities = {str(value).upper() for value in card.get("capabilities", [])}
        if (
            card.get("status") == "online"
            and capabilities & WORKER_CAPABILITIES
            and agent_is_recent(card.get("last_seen"))
        ):
            workers.append(card)
    return workers


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


def agent_endpoint(card: JsonObject) -> str:
    endpoint = str(card.get("endpoint", "")).rstrip("/")
    if not endpoint:
        raise ValueError(f"Agent {card.get('agent_id', 'unknown')!r} has no endpoint.")

    local_api = "127.0.0.1" in API_URL or "localhost" in API_URL
    if local_api:
        local_ports = {
            "langgraph-copilot": 8101,
            "googleADK-Chatagent": 8102,
        }
        port = local_ports.get(str(card.get("agent_id")))
        if port is not None:
            return f"http://127.0.0.1:{port}"
    return endpoint


def invoke_agent(card: JsonObject, prompt: str) -> JsonObject:
    response = httpx.post(
        f"{agent_endpoint(card)}/invoke",
        json={
            "message": prompt,
            "approval_required": card.get("agent_id") == "langgraph-copilot",
            "thread_id": str(uuid4()),
        },
        timeout=AGENT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def resume_agent(card: JsonObject, thread_id: str, decision: str) -> JsonObject:
    response = httpx.post(
        f"{agent_endpoint(card)}/conversations/{thread_id}/resume",
        json={"decision": decision},
        timeout=AGENT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def normalize_human_options(options: Sequence[Any] | None) -> list[dict[str, str]]:
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


def extract_human_input(result: JsonObject, agent_id: str) -> JsonObject | None:
    if result.get("status") != "awaiting_human":
        return None
    interrupt_payload = result.get("interrupt", {})
    if not isinstance(interrupt_payload, dict):
        interrupt_payload = {"prompt": str(interrupt_payload)}
    return {
        "agent_id": agent_id,
        "thread_id": result["thread_id"],
        "prompt": interrupt_payload.get("prompt", "Human input is required."),
        "draft_reply": result.get("draft_reply") or interrupt_payload.get("draft_reply", ""),
        "options": normalize_human_options(interrupt_payload.get("options")),
        "llm_model": result.get("llm_model", "unknown"),
    }


def result_text(result: JsonObject) -> str:
    return str(
        result.get("final_reply")
        or result.get("draft_reply")
        or result.get("answer")
        or "The agent returned no text response."
    )


def start_master_workflow(goal: str, selected_agents: list[str]) -> JsonObject:
    if not goal.strip():
        raise ValueError("Workflow goal cannot be empty.")
    response = httpx.post(
        f"{API_URL}/workflows/start",
        json={
            "conversation_id": f"streamlit-{uuid4()}",
            "goal": goal.strip(),
            "preferred_agent_ids": selected_agents,
        },
        timeout=AGENT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def submit_workflow_approval(workflow_id: str, decision: str) -> JsonObject:
    response = httpx.post(
        f"{API_URL}/workflows/{workflow_id}/approvals",
        json={
            "decision": decision.strip().upper(),
            "feedback": "",
            "actor": "streamlit-user",
            "edits": {},
        },
        timeout=AGENT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def refresh_workflow(workflow_id: str) -> JsonObject:
    response = httpx.get(
        f"{API_URL}/workflows/{workflow_id}",
        timeout=10.0,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def postgres_url() -> str:
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def fetch_postgres_rows(query: str, params: tuple[Any, ...]) -> list[JsonObject]:
    try:
        with psycopg.connect(postgres_url(), row_factory=dict_row, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
    except psycopg.Error:
        return []


def fetch_resource_rows(limit: int = 100) -> list[JsonObject]:
    return fetch_postgres_rows(
        """
        SELECT resource_id, resource_type, name, status, endpoint, owner,
               capabilities, parent_resource_id, last_seen, updated_at
        FROM agentmesh_resources
        ORDER BY resource_type ASC, name ASC
        LIMIT %s
        """,
        (limit,),
    )


def fetch_audit_rows(limit: int = 100) -> list[JsonObject]:
    return fetch_postgres_rows(
        """
        SELECT audit_id::text AS audit_id, resource_id, event_type, severity, actor, message,
               workflow_id::text AS workflow_id, event_id::text AS event_id, created_at
        FROM agentmesh_resource_audit_events
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def fetch_workflow_events(workflow_id: str) -> list[JsonObject]:
    return fetch_postgres_rows(
        """
        SELECT sequence_number, timestamp, event_type, source_agent,
               routing_mode, target_agent
        FROM agentmesh_events
        WHERE workflow_id = %s
        ORDER BY sequence_number ASC
        """,
        (workflow_id,),
    )


def clear_agent_chat() -> None:
    selected = st.session_state.get("selected_agent_id", "agent")
    st.session_state.agent_messages = [
        {"role": "assistant", "content": f"Ready to talk with {selected}."}
    ]
    st.session_state.pending_human_input = None


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


def render_workflow_plan(
    workflow_id: str,
    tasks: list[JsonObject],
    task_results: list[JsonObject],
) -> None:
    """Render plan rows with controls for inspecting agent input and output."""

    results_by_task_id = {
        str(item.get("task_id")): item.get("result", {})
        for item in task_results
        if isinstance(item, dict) and item.get("task_id")
    }
    headers = st.columns([0.6, 2.4, 2, 1.4, 1, 1])
    for column, label in zip(
        headers,
        ["Step", "Task", "Agent", "Capability", "Input", "Output"],
        strict=True,
    ):
        column.caption(label)

    for task in tasks:
        task_id = str(task.get("task_id", ""))
        agent_id = str(task.get("agent_id", "worker"))
        task_name = str(task.get("name", "Task"))
        columns = st.columns([0.6, 2.4, 2, 1.4, 1, 1])
        columns[0].write(str(int(task.get("position", 0)) + 1))
        columns[1].write(task_name)
        columns[2].write(agent_id)
        columns[3].write(str(task.get("required_capability", "")))
        input_column = columns[4]
        output_column = columns[5]
        if input_column.button(
            "Input",
            key=f"workflow-input-{workflow_id}-{task_id}",
            width="stretch",
        ):
            st.session_state.workflow_task_io = {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "kind": "Input",
                "value": task,
            }
        if output_column.button(
            "Output",
            key=f"workflow-output-{workflow_id}-{task_id}",
            width="stretch",
            disabled=task_id not in results_by_task_id,
        ):
            st.session_state.workflow_task_io = {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "kind": "Output",
                "value": results_by_task_id[task_id],
            }

    selected = st.session_state.get("workflow_task_io")
    if isinstance(selected, dict) and selected.get("workflow_id") == workflow_id:
        st.caption(f"{selected['agent_id']} - {selected['kind']}")
        st.json(selected.get("value", {}), expanded=True)


st.set_page_config(page_title="AgentMesh", layout="wide")
st.sidebar.title("AgentMesh")
page = st.sidebar.radio(
    "Navigation",
    ["Resource Dashboard", "Agent Playground", "Orchestration Playground"],
)

registered_agents = fetch_registered_agents()
worker_cards = worker_agent_cards(registered_agents)
worker_cards_by_id = {str(card["agent_id"]): card for card in worker_cards}
worker_ids = list(worker_cards_by_id)

if page == "Resource Dashboard":
    st.title("Resource Dashboard")
    resource_rows = fetch_resource_rows()
    total_resources = len(resource_rows)
    active_resources = sum(row.get("status") == "online" for row in resource_rows)
    stale_resources = sum(row.get("status") == "stale" for row in resource_rows)

    metric_columns = st.columns(3)
    metric_columns[0].metric("Resources", total_resources)
    metric_columns[1].metric("Active", active_resources)
    metric_columns[2].metric("Stale", stale_resources)

    if st.button("Refresh data"):
        st.rerun()

    st.subheader("Resources")
    if resource_rows:
        st.dataframe(resource_rows, width="stretch", hide_index=True)
    else:
        st.info("No resources found in PostgreSQL.")

    st.subheader("Resource Audit Trail")
    audit_rows = fetch_audit_rows()
    if audit_rows:
        st.dataframe(audit_rows, width="stretch", hide_index=True)
    else:
        st.info("No resource audit events found in PostgreSQL.")

elif page == "Agent Playground":
    st.title("Agent Playground")
    if not worker_ids:
        st.warning("No online worker agents are registered.")
        st.stop()

    if st.session_state.get("selected_agent_id") not in worker_ids:
        st.session_state.selected_agent_id = worker_ids[0]
        clear_agent_chat()
    selected_agent_id = str(
        st.selectbox(
            "Agent",
            options=worker_ids,
            key="selected_agent_id",
            on_change=clear_agent_chat,
        )
    )
    selected_card = worker_cards_by_id[selected_agent_id]

    for message in st.session_state.agent_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    pending = st.session_state.pending_human_input
    if pending:
        st.subheader("Approval required")
        st.caption(f"Model: {pending['llm_model']}")
        st.write(pending["prompt"])
        if pending["draft_reply"]:
            st.info(pending["draft_reply"])
        option_columns = st.columns(len(pending["options"]))
        for index, option in enumerate(pending["options"]):
            with option_columns[index]:
                if st.button(option["label"].title(), width="stretch"):
                    try:
                        with st.spinner(f"{selected_agent_id} is processing your decision..."):
                            result = resume_agent(
                                selected_card,
                                pending["thread_id"],
                                option["value"],
                            )
                        st.session_state.agent_messages.append(
                            {"role": "assistant", "content": result_text(result)}
                        )
                        st.session_state.pending_human_input = None
                        st.rerun()
                    except (ValueError, httpx.HTTPError) as exc:
                        st.error(str(exc))

    prompt = st.chat_input("Message agent", disabled=bool(pending))
    if prompt:
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        try:
            with st.spinner(f"{selected_agent_id} is processing your request..."):
                result = invoke_agent(selected_card, prompt)
            human_input = extract_human_input(result, selected_agent_id)
            if human_input:
                st.session_state.pending_human_input = human_input
                st.session_state.agent_messages.append(
                    {
                        "role": "assistant",
                        "content": f"Draft ready. {human_input['prompt']}",
                    }
                )
            else:
                st.session_state.agent_messages.append(
                    {"role": "assistant", "content": result_text(result)}
                )
            st.rerun()
        except (ValueError, httpx.HTTPError) as exc:
            st.error(str(exc))

else:
    st.title("Orchestration Playground")
    workflow_goal = st.text_area(
        "Workflow goal",
        placeholder="Describe the result you want the orchestrator to produce",
    )
    preferred_agents = cast(
        list[str],
        st.multiselect("Preferred agents", options=worker_ids),
    )

    if st.button("Start workflow", type="primary", disabled=not workflow_goal.strip()):
        try:
            with st.spinner("Orchestrator is planning the workflow..."):
                st.session_state.workflow_result = start_master_workflow(
                    workflow_goal,
                    preferred_agents,
                )
                st.session_state.pop("workflow_task_io", None)
            st.rerun()
        except (ValueError, httpx.HTTPError) as exc:
            st.error(str(exc))

    workflow = st.session_state.get("workflow_result")
    if workflow:
        workflow_id = str(workflow["workflow_id"])
        st.subheader("Workflow")
        st.caption(f"Workflow ID: {workflow_id}")
        st.write(f"Status: {workflow['status']}")

        plan = workflow.get("plan") or {}
        tasks = plan.get("tasks", [])
        if tasks:
            st.subheader("Plan")
            render_workflow_plan(
                workflow_id,
                cast(list[JsonObject], tasks),
                cast(list[JsonObject], workflow.get("task_results", [])),
            )

        st.subheader("Workflow Event Trail")
        event_rows = fetch_workflow_events(workflow_id)
        if event_rows:
            st.dataframe(event_rows, width="stretch", hide_index=True)
        else:
            st.info("Waiting for workflow events to reach PostgreSQL.")

        pending_input = workflow.get("pending_input") or {}
        if pending_input.get("type") == "human_approval":
            st.write(pending_input.get("prompt", "Approval is required."))
            options = normalize_human_options(pending_input.get("options"))
            approval_columns = st.columns(len(options))
            for index, option in enumerate(options):
                with approval_columns[index]:
                    if st.button(
                        option["label"],
                        key=f"workflow-{workflow_id}-{option['value']}",
                        width="stretch",
                    ):
                        try:
                            with st.spinner("Orchestrator is applying your decision..."):
                                st.session_state.workflow_result = submit_workflow_approval(
                                    workflow_id,
                                    option["value"],
                                )
                            st.rerun()
                        except httpx.HTTPError as exc:
                            st.error(str(exc))

        elif workflow["status"] == "WAITING_FOR_AGENT":
            current_task = workflow.get("current_task") or {}
            with st.status(
                f"Waiting for {current_task.get('agent_id', 'worker')}...",
                expanded=False,
                state="running",
            ):
                st.write(current_task.get("name", "Processing assigned task"))
            time.sleep(2)
            try:
                st.session_state.workflow_result = refresh_workflow(workflow_id)
                st.rerun()
            except httpx.HTTPError as exc:
                st.error(str(exc))

        elif workflow["status"] in TERMINAL_WORKFLOW_STATUSES:
            answer = workflow_answer(workflow)
            if answer:
                st.subheader("Answer")
                st.markdown(answer)
            elif workflow["status"] == "COMPLETED":
                st.info("Workflow completed without a text result.")
