from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import streamlit as st

from agentmesh.agents.langgraph_copilot.agent import ConversationAgent
from agentmesh.agents.adk_spark.agent import GoogleADKAgent
from agentmesh.services.orchestrator_service import AgentStep, OrchestratorService


def fetch_registered_agents() -> list[dict]:
    registry_url = os.getenv("AGENT_REGISTRY_URL", "http://127.0.0.1:8000/registry/agents")
    try:
        response = httpx.get(registry_url, timeout=3.0)
        if response.status_code == 200:
            return response.json()
    except httpx.HTTPError:
        return []
    return []


def format_last_seen(value: str | None) -> str:
    if not value:
        return "never"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
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
    selected_agent = st.session_state.agent
    if agent_name == st.session_state.google_adk_agent.agent_name:
        return st.session_state.google_adk_agent
    if agent_name != selected_agent.agent_name:
        if agent_name not in st.session_state.dynamic_agents:
            st.session_state.dynamic_agents[agent_name] = ConversationAgent(
                agent_name=agent_name,
                auto_register=False,
            )
        return st.session_state.dynamic_agents[agent_name]
    return selected_agent


def run_agent_conversation(agent: ConversationAgent | GoogleADKAgent, prompt: str) -> dict:
    if hasattr(agent, "start_conversation"):
        return agent.start_conversation(prompt, thread_id=str(uuid4()))
    return agent.run_conversation(prompt)


def resume_agent_conversation(
    agent: ConversationAgent | GoogleADKAgent,
    thread_id: str,
    human_response: str,
) -> dict:
    if not hasattr(agent, "resume_conversation"):
        raise ValueError(f"Agent {agent.agent_name!r} cannot resume human input.")
    return agent.resume_conversation(thread_id, human_response)


def normalize_human_options(options: list | tuple | None) -> list[dict[str, str]]:
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


def extract_human_input_request(result: dict, agent_name: str) -> dict | None:
    if result.get("status") != "awaiting_human":
        return None

    interrupt_payload = result.get("interrupt", {})
    if not isinstance(interrupt_payload, dict):
        interrupt_payload = {"prompt": str(interrupt_payload)}

    options = normalize_human_options(interrupt_payload.get("options"))
    return {
        "agent_name": agent_name,
        "thread_id": result["thread_id"],
        "type": interrupt_payload.get("type", "human_input"),
        "prompt": interrupt_payload.get("prompt", "Human input is required."),
        "draft_reply": result.get("draft_reply") or interrupt_payload.get("draft_reply", ""),
        "options": options,
    }


def build_workflow_plan(goal: str, selected_agents: list[str]) -> dict:
    if not goal.strip():
        raise ValueError("Workflow goal cannot be empty.")
    if not selected_agents:
        raise ValueError("Select at least one agent for the workflow.")

    steps = [
        AgentStep(f"step_{idx + 1}", "CHAT", agent_name, f"Route request for: {goal}")
        for idx, agent_name in enumerate(selected_agents)
    ]
    service = OrchestratorService(steps)
    state, events = service.start_workflow("conversation-ui", goal, workflow_id=uuid4())
    return {"state": state, "events": events, "steps": steps}


def run_realtime_workflow(goal: str, selected_agents: list[str]) -> list[str]:
    progress: list[str] = []
    progress.append(f"[start] workflow goal: {goal}")
    for index, agent_name in enumerate(selected_agents, start=1):
        progress.append(f"[task {index}] assigning '{agent_name}'")
        time.sleep(0.6)
        progress.append(f"[task {index}] {agent_name} started processing")
        time.sleep(0.6)
        progress.append(f"[task {index}] {agent_name} completed")
    progress.append("[done] workflow finished")
    return progress


st.set_page_config(page_title="AgentMesh Chat", layout="wide")
st.title("AgentMesh Local Chat")

registry_url = os.getenv("AGENT_REGISTRY_URL", "http://127.0.0.1:8000/registry/agents")
st.sidebar.subheader("Registry")
st.sidebar.caption(f"Registry URL: {registry_url}")

if "agent" not in st.session_state:
    st.session_state.agent = ConversationAgent(auto_register=True)
if "google_adk_agent" not in st.session_state:
    st.session_state.google_adk_agent = GoogleADKAgent(auto_register=True)
if "dynamic_agents" not in st.session_state:
    st.session_state.dynamic_agents = {}

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hi! I am the conversation agent. Ask me anything."}]
if "workflow_tasks" not in st.session_state:
    st.session_state.workflow_tasks = []
if "pending_human_input" not in st.session_state:
    st.session_state.pending_human_input = None

registered_agents = fetch_registered_agents()
if registered_agents:
    st.sidebar.write("Registered agents:")
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
    st.sidebar.dataframe(agent_rows, use_container_width=True)
else:
    st.sidebar.write("No agents are currently registered.")

agent_options = [
    agent.get("name", agent.get("agent_id", "langgraph-copilot"))
    for agent in registered_agents
]
if not agent_options:
    agent_options = [st.session_state.agent.agent_name, st.session_state.google_adk_agent.agent_name]
selected_agent_name = st.sidebar.selectbox("Choose agent", options=agent_options)

st.sidebar.subheader("Workflow")
workflow_goal = st.sidebar.text_input("Workflow goal", value="Help with this request")
workflow_agents = st.sidebar.multiselect(
    "Select agents for workflow",
    options=agent_options,
    default=agent_options[: min(3, len(agent_options))],
)
if st.sidebar.button("Start workflow"):
    try:
        workflow = build_workflow_plan(workflow_goal, workflow_agents)
        st.session_state.workflow_result = workflow
        st.session_state.workflow_tasks = run_realtime_workflow(workflow_goal, workflow_agents)
        st.sidebar.success("Workflow launched successfully.")
    except ValueError as exc:
        st.sidebar.error(str(exc))

if "workflow_result" in st.session_state:
    workflow_result = st.session_state.workflow_result
    st.subheader("Workflow plan")
    st.write(f"Workflow ID: {workflow_result['state'].workflow_id}")
    st.write(f"Status: {workflow_result['state'].status}")
    for step in workflow_result["steps"]:
        st.write(f"- {step.name}: {step.task_type} -> {step.agent}")

    if st.session_state.workflow_tasks:
        st.subheader("Task activity")
        for task in st.session_state.workflow_tasks:
            st.write(task)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

pending_human_input = st.session_state.pending_human_input
if pending_human_input:
    st.subheader("Human input")
    st.caption(f"Requested by {pending_human_input['agent_name']}")
    st.write(pending_human_input["prompt"])
    if pending_human_input["draft_reply"]:
        st.info(pending_human_input["draft_reply"])

    option_columns = st.columns(len(pending_human_input["options"]))
    for index, option in enumerate(pending_human_input["options"]):
        with option_columns[index]:
            if st.button(option["label"].title(), use_container_width=True):
                pending_agent = get_selected_agent(pending_human_input["agent_name"])
                result = resume_agent_conversation(
                    pending_agent,
                    pending_human_input["thread_id"],
                    option["value"],
                )
                reply = result.get("final_reply") or result.get("draft_reply") or f"Selected: {option['label']}"
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
        reply = result.get("final_reply") or result.get("draft_reply") or "I do not have a response yet."
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.write(reply)
