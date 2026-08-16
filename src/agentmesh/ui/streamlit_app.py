from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypeAlias, cast
from uuid import uuid4

import httpx
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from agentmesh.agents.adk_spark.agent import GoogleADKAgent
from agentmesh.agents.langgraph_copilot.agent import ConversationAgent

API_URL = os.getenv("AGENTMESH_API_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh",
)
JsonObject: TypeAlias = dict[str, Any]


def fetch_registered_agents() -> list[JsonObject]:
    registry_url = os.getenv("AGENT_REGISTRY_URL", "http://127.0.0.1:8000/registry/agents")
    try:
        response = httpx.get(registry_url, timeout=3.0)
        if response.status_code == 200:
            return cast(list[JsonObject], response.json())
    except httpx.HTTPError:
        return []
    return []


def format_last_seen(value: str | None) -> str:
    if not value:
        return "never"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return str(value)


def register_agent_manually(agent: ConversationAgent | GoogleADKAgent) -> None:
    payload = {
        "agent_id": agent.agent_name,
        "name": agent.agent_name,
        "version": "1.0.0",
        "description": getattr(agent, "description", "Local agent"),
        "endpoint": os.getenv("AGENT_ENDPOINT", "http://localhost:8001"),
        "capabilities": getattr(agent, "capabilities", ["CHAT"]),
        "skills": getattr(agent, "skills", ["conversation"]),
        "owner": "platform-team",
        "status": "online",
    }
    try:
        httpx.post(
            os.getenv("AGENT_REGISTRY_URL", "http://127.0.0.1:8000/registry/agents"),
            json=payload,
            timeout=3.0,
        )
    except httpx.HTTPError:
        st.sidebar.warning("Registry is not reachable right now.")


def get_selected_agent(agent_name: str) -> ConversationAgent | GoogleADKAgent:
    selected_agent = cast(ConversationAgent, st.session_state.agent)
    if agent_name == st.session_state.google_adk_agent.agent_name:
        return cast(GoogleADKAgent, st.session_state.google_adk_agent)
    if agent_name != selected_agent.agent_name:
        dynamic_agents = cast(dict[str, ConversationAgent], st.session_state.dynamic_agents)
        if agent_name not in dynamic_agents:
            dynamic_agents[agent_name] = ConversationAgent(
                agent_name=agent_name,
                auto_register=False,
            )
        return dynamic_agents[agent_name]
    return selected_agent


def run_agent_conversation(
    agent: ConversationAgent | GoogleADKAgent,
    prompt: str,
) -> JsonObject:
    if isinstance(agent, ConversationAgent):
        return agent.start_conversation(prompt, thread_id=str(uuid4()))
    return agent.run_conversation(prompt)


def resume_agent_conversation(
    agent: ConversationAgent | GoogleADKAgent,
    thread_id: str,
    human_response: str,
) -> JsonObject:
    if not isinstance(agent, ConversationAgent):
        raise ValueError(f"Agent {agent.agent_name!r} cannot resume human input.")
    return agent.resume_conversation(thread_id, human_response)


def normalize_human_options(options: Sequence[Any] | None) -> list[dict[str, str]]:
    if not options:
        options = ["approve", "reject"]

    normalized_options = []
    for option in options:
        if isinstance(option, dict):
            value = str(option.get("value", option.get("label", "")))
            label = str(option.get("label", value))
        else:
            value = str(option)
            label = value
        if value:
            normalized_options.append({"label": label, "value": value})
    return normalized_options or [
        {"label": "approve", "value": "approve"},
        {"label": "reject", "value": "reject"},
    ]


def extract_human_input_request(result: JsonObject, agent_name: str) -> JsonObject | None:
    if result.get("status") != "awaiting_human":
        return None

    interrupt_payload = result.get("interrupt", {})
    if not isinstance(interrupt_payload, dict):
        interrupt_payload = {"prompt": str(interrupt_payload)}

    options = normalize_human_options(interrupt_payload.get("options"))
    if not options:
        options = normalize_human_options(result.get("options"))

    return {
        "agent_name": agent_name,
        "thread_id": result["thread_id"],
        "type": interrupt_payload.get("type", "human_input"),
        "prompt": interrupt_payload.get("prompt", "Human input is required."),
        "draft_reply": result.get("draft_reply") or interrupt_payload.get("draft_reply", ""),
        "options": options,
        "llm_model": result.get("llm_model", "local-model"),
    }


def start_master_workflow(goal: str, selected_agents: list[str]) -> JsonObject:
    if not goal.strip():
        raise ValueError("Workflow goal cannot be empty.")
    response = httpx.post(
        f"{API_URL}/workflows/start",
        json={
            "conversation_id": f"conversation-ui-{uuid4()}",
            "goal": goal,
            "preferred_agent_ids": selected_agents or [],
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def submit_workflow_approval(
    workflow_id: str,
    decision: str,
    feedback: str,
) -> JsonObject:
    response = httpx.post(
        f"{API_URL}/workflows/{workflow_id}/approvals",
        json={
            "decision": decision.strip().upper(),
            "feedback": feedback,
            "actor": "streamlit-user",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return cast(JsonObject, response.json())


def refresh_workflow(workflow_id: str) -> JsonObject:
    response = httpx.get(f"{API_URL}/workflows/{workflow_id}", timeout=5.0)
    response.raise_for_status()
    return cast(JsonObject, response.json())


def postgres_url() -> str:
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def fetch_resource_rows(limit: int = 100) -> list[JsonObject]:
    query = """
        SELECT
            resource_id,
            resource_type,
            name,
            status,
            endpoint,
            owner,
            capabilities,
            parent_resource_id,
            last_seen,
            updated_at
        FROM agentmesh_resources
        ORDER BY resource_type ASC, name ASC
        LIMIT %s
    """
    return fetch_postgres_rows(query, (limit,))


def fetch_audit_rows(limit: int = 100) -> list[JsonObject]:
    query = """
        SELECT
            audit_id,
            resource_id,
            event_type,
            severity,
            actor,
            message,
            workflow_id,
            event_id,
            created_at
        FROM agentmesh_resource_audit_events
        ORDER BY created_at DESC
        LIMIT %s
    """
    return fetch_postgres_rows(query, (limit,))


def fetch_recent_workflow_events(limit: int = 100) -> list[JsonObject]:
    query = """
        SELECT
            event_id,
            conversation_id,
            workflow_id,
            timestamp,
            event_type,
            source_agent,
            routing_mode,
            target_agent,
            sequence_number
        FROM agentmesh_events
        ORDER BY timestamp DESC, sequence_number DESC
        LIMIT %s
    """
    return fetch_postgres_rows(query, (limit,))


def fetch_postgres_rows(query: str, params: tuple[Any, ...]) -> list[JsonObject]:
    try:
        with psycopg.connect(postgres_url(), row_factory=dict_row, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
    except psycopg.Error:
        return []


st.set_page_config(page_title="AgentMesh Chat", layout="wide")

st.sidebar.markdown(
    """
    <div style="padding:12px 14px; border-radius:12px;
                background:linear-gradient(135deg, #1f2937, #111827);
                color:white; margin-bottom:14px;">
        <div style="font-size:1.1rem; font-weight:700;">AgentMesh</div>
        <div style="font-size:0.75rem; opacity:0.8;">Local orchestration workspace</div>
    </div>
    """,
    unsafe_allow_html=True,
)

registry_url = os.getenv("AGENT_REGISTRY_URL", "http://127.0.0.1:8000/registry/agents")

if "agent" not in st.session_state:
    st.session_state.agent = ConversationAgent(auto_register=True)
if "google_adk_agent" not in st.session_state:
    st.session_state.google_adk_agent = GoogleADKAgent(auto_register=True)
if "dynamic_agents" not in st.session_state:
    st.session_state.dynamic_agents = {}

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hi! I am the conversation agent. Ask me anything."}
    ]
if "pending_human_input" not in st.session_state:
    st.session_state.pending_human_input = None

registered_agents = fetch_registered_agents()
if registered_agents:
    agent_rows = []
    for agent in registered_agents:
        agent_rows.append(
            {
                "name": agent.get("name", agent.get("agent_id")),
                "status": agent.get("status", "online"),
                "capabilities": ", ".join(agent.get("capabilities", [])),
                "last_seen": format_last_seen(agent.get("last_seen")),
            }
        )
else:
    agent_rows = []

agent_options: list[str] = [
    str(agent.get("name") or agent.get("agent_id") or "langgraph-copilot")
    for agent in registered_agents
]
if not agent_options:
    agent_options = [
        st.session_state.agent.agent_name,
        st.session_state.google_adk_agent.agent_name,
    ]

page = st.sidebar.radio(
    "Navigation",
    ["📊 Resource Dashboard", "🎯 Agent Playground", "⚙️ Orchestration Playground"],
    index=0,
)

st.sidebar.subheader("Registry")
st.sidebar.caption(f"Registry URL: {registry_url}")
if agent_rows:
    st.sidebar.write("Registered agents:")
    st.sidebar.dataframe(agent_rows, width="stretch")
else:
    st.sidebar.write("No agents are currently registered.")

selected_agent_name = str(st.sidebar.selectbox("Choose agent", options=agent_options))

if page == "📊 Resource Dashboard":
    st.title("Resource Dashboard")
    st.caption("Operational view backed by PostgreSQL resources, audits, and workflow events.")

    resource_rows = fetch_resource_rows()
    audit_rows = fetch_audit_rows()
    workflow_event_rows = fetch_recent_workflow_events()

    total_resources = len(resource_rows)
    online_resources = len([row for row in resource_rows if row.get("status") == "online"])
    failed_resources = len([row for row in resource_rows if row.get("status") == "failed"])
    recent_audits = len(audit_rows)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Resources", total_resources)
    metric_cols[1].metric("Online", online_resources)
    metric_cols[2].metric("Failed", failed_resources)
    metric_cols[3].metric("Recent audits", recent_audits)

    st.subheader("Resources")
    if resource_rows:
        st.dataframe(resource_rows, width="stretch", hide_index=True)
    else:
        st.info(
            "No rows found in agentmesh_resources. Start Postgres and apply "
            "db/postgress/ddls before using this dashboard."
        )

    st.subheader("Resource Audit Trail")
    if audit_rows:
        st.dataframe(audit_rows, width="stretch", hide_index=True)
    else:
        st.info("No audit events found yet.")

    st.subheader("Workflow Timeline")
    if workflow_event_rows:
        st.dataframe(workflow_event_rows, width="stretch", hide_index=True)
    else:
        st.info("No workflow events found yet.")

elif page == "🎯 Agent Playground":
    st.title("Agent Playground")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    pending_human_input = st.session_state.pending_human_input
    if pending_human_input:
        st.subheader("Human approval required")
        st.caption(f"Requested by {pending_human_input['agent_name']}")
        st.caption(f"LLM: {pending_human_input.get('llm_model', 'local-model')}")
        st.write(pending_human_input["prompt"])
        if pending_human_input["draft_reply"]:
            st.info(pending_human_input["draft_reply"])

        options = normalize_human_options(pending_human_input.get("options"))
        option_columns = st.columns(len(options))
        for index, option in enumerate(options):
            with option_columns[index]:
                if st.button(option["label"].title(), width="stretch"):
                    pending_agent = get_selected_agent(pending_human_input["agent_name"])
                    result = resume_agent_conversation(
                        pending_agent,
                        pending_human_input["thread_id"],
                        option["value"],
                    )
                    reply = (
                        result.get("final_reply")
                        or result.get("draft_reply")
                        or f"Selected: {option['label']}"
                    )
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.session_state.pending_human_input = None
                    st.rerun()

    prompt = st.chat_input("Type your message", disabled=bool(st.session_state.pending_human_input))
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        selected_agent = get_selected_agent(selected_agent_name)
        result = run_agent_conversation(selected_agent, prompt)
        human_input_request = extract_human_input_request(result, selected_agent.agent_name)
        if human_input_request:
            st.session_state.pending_human_input = human_input_request
            draft_reply = human_input_request["draft_reply"]
            message = f"Waiting for human input: {human_input_request['prompt']}"
            if draft_reply:
                message = f"{message}\n\nDraft: {draft_reply}"
            st.session_state.messages.append({"role": "assistant", "content": message})
            st.rerun()
        else:
            reply = (
                result.get("final_reply")
                or result.get("draft_reply")
                or "I do not have a response yet."
            )
            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.write(reply)

else:
    st.title("Orchestration Playground")
    st.caption(
        "The planner automatically selects the best-fit agent(s) from the registry "
        "when no manual selection is provided."
    )

    workflow_goal = st.text_input("Workflow goal", value="Help with this request")
    workflow_agents = cast(
        list[str],
        st.multiselect("Preferred agents", options=agent_options, default=[]),
    )
    if st.button("Start workflow", type="primary"):
        try:
            st.session_state.workflow_result = start_master_workflow(
                workflow_goal, workflow_agents
            )
            st.success("Plan created. The planner selected agents automatically from the registry.")
            st.rerun()
        except (ValueError, httpx.HTTPError) as exc:
            st.error(str(exc))

    if "workflow_result" in st.session_state:
        workflow_result = st.session_state.workflow_result
        st.subheader("Workflow plan")
        st.caption(f"Workflow ID: {workflow_result['workflow_id']}")
        st.write(f"Status: {workflow_result['status']}")
        plan = workflow_result.get("plan") or {}
        planner_name = plan.get("planner_provider", "unknown")
        planner_model = plan.get("planner_model")
        planner_label = f"Planner: {planner_name}"
        if planner_model:
            planner_label = f"{planner_label} ({planner_model})"
        st.caption(planner_label)
        for task in plan.get("tasks", []):
            st.write(
                f"{task['position'] + 1}. {task['name']} -> {task['agent_id']} "
                f"({task['required_capability']})"
            )

        pending_workflow_input = workflow_result.get("pending_input") or {}
        if pending_workflow_input.get("type") == "human_approval":
            st.write(pending_workflow_input.get("prompt", "Human approval is required."))
            approval = pending_workflow_input.get("approval", {})
            approval_feedback = st.text_area(
                "Feedback or revision guidance",
                key=f"workflow-feedback-{approval.get('approval_id', 'pending')}",
            )
            options = normalize_human_options(pending_workflow_input.get("options"))
            approval_columns = st.columns(len(options))
            for index, option in enumerate(options):
                with approval_columns[index]:
                    if st.button(
                        option["label"],
                        key=f"workflow-{approval.get('approval_id')}-{option['value']}",
                        width="stretch",
                    ):
                        try:
                            st.session_state.workflow_result = submit_workflow_approval(
                                workflow_result["workflow_id"],
                                option["value"],
                                approval_feedback,
                            )
                            st.rerun()
                        except httpx.HTTPError as exc:
                            st.error(str(exc))
        elif pending_workflow_input.get("type") == "agent_result":
            task = pending_workflow_input.get("task", {})
            st.info(
                f"Waiting for {task.get('agent_id', 'worker')} to complete "
                f"{task.get('name', 'the assigned task')}."
            )
            if st.button("Refresh workflow", width="content"):
                try:
                    st.session_state.workflow_result = refresh_workflow(
                        workflow_result["workflow_id"]
                    )
                    st.rerun()
                except httpx.HTTPError as exc:
                    st.error(str(exc))
