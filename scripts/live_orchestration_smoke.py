from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import httpx

from agentmesh.agents.agent_adk_spark.factory import create_google_adk_worker_agent
from agentmesh.agents.agent_langgraph_copilot.factory import create_langgraph_worker_agent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.control_plane_client import ControlPlaneClient
from agentmesh.agents.common.worker import AssignmentWorker
from agentmesh.config import Settings, get_settings

AgentFactory = Callable[[Settings], tuple[BaseAgent, Callable[[], None]]]


def build_worker(
    factory: AgentFactory,
    settings: Settings,
    api_url: str,
) -> tuple[AssignmentWorker, Callable[[], None]]:
    agent, close_agent = factory(settings)
    client = ControlPlaneClient(
        api_url, timeout_seconds=settings.worker_request_timeout_seconds
    )
    worker = AssignmentWorker(
        agent,
        client,
        poll_interval_seconds=settings.poll_interval_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
    )

    def close() -> None:
        client.close()
        close_agent()

    return worker, close


def start_workflow(
    client: httpx.Client,
    *,
    goal: str,
    preferred_agents: list[str],
) -> dict[str, Any]:
    response = client.post(
        "/workflows/start",
        json={
            "conversation_id": f"live-smoke-{uuid4()}",
            "goal": goal,
            "preferred_agent_ids": preferred_agents,
        },
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def approve(client: httpx.Client, workflow_id: str) -> dict[str, Any]:
    response = client.post(
        f"/workflows/{workflow_id}/approvals",
        json={"decision": "APPROVE", "actor": "live-smoke"},
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def run_workflow(
    client: httpx.Client,
    workers: dict[str, AssignmentWorker],
    *,
    goal: str,
    preferred_agents: list[str],
) -> dict[str, Any]:
    state = start_workflow(client, goal=goal, preferred_agents=preferred_agents)
    planned_agents = [task["agent_id"] for task in state["plan"]["tasks"]]
    state = approve(client, state["workflow_id"])
    while state["status"] != "COMPLETED":
        if state["status"] != "WAITING_FOR_AGENT":
            raise RuntimeError(f"Unexpected workflow state: {state['status']}")
        assigned_agent = state["current_task"]["agent_id"]
        if not workers[assigned_agent].run_once():
            raise RuntimeError(f"Worker {assigned_agent} did not find its assignment.")
        response = client.get(f"/workflows/{state['workflow_id']}")
        response.raise_for_status()
        state = cast(dict[str, Any], response.json())
    return {
        "workflow_id": state["workflow_id"],
        "status": state["status"],
        "planned_agents": planned_agents,
        "result_count": len(state["task_results"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live AgentMesh orchestration scenarios.")
    parser.add_argument("--api-url", help="Override AGENTMESH_API_URL.")
    args = parser.parse_args()
    settings = get_settings()
    api_url = args.api_url or settings.agentmesh_api_url
    summary: dict[str, Any] = {}
    with httpx.Client(base_url=api_url, timeout=60.0) as api_client:
        empty_workflow_id = str(uuid4())
        no_agent = api_client.post(
            "/workflows/start",
            json={
                "conversation_id": "live-smoke-no-agent",
                "workflow_id": empty_workflow_id,
                "goal": "Create a concise event-sourcing explanation.",
            },
        )
        failed_state = api_client.get(f"/state/{empty_workflow_id}")
        failed_state.raise_for_status()
        summary["no_agent"] = {
            "http_status": no_agent.status_code,
            "workflow_status": failed_state.json()["status"],
        }

        langgraph, close_langgraph = build_worker(
            create_langgraph_worker_agent, settings, api_url
        )
        google_adk, close_google_adk = build_worker(
            create_google_adk_worker_agent, settings, api_url
        )
        try:
            langgraph.run_once()
            google_adk.run_once()
            workers = {
                langgraph.agent.agent_name: langgraph,
                google_adk.agent.agent_name: google_adk,
            }
            summary["langgraph_only"] = run_workflow(
                api_client,
                workers,
                goal="Explain event sourcing in two concise sentences.",
                preferred_agents=[langgraph.agent.agent_name],
            )
            summary["google_adk_only"] = run_workflow(
                api_client,
                workers,
                goal="Explain human approval gates in two concise sentences.",
                preferred_agents=[google_adk.agent.agent_name],
            )
            summary["all_agents"] = run_workflow(
                api_client,
                workers,
                goal="Draft and review a concise explanation of reliable agent orchestration.",
                preferred_agents=list(workers),
            )
        finally:
            close_google_adk()
            close_langgraph()

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
