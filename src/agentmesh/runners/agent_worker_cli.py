from __future__ import annotations

import argparse
import json
from collections.abc import Callable

from agentmesh.agents.base import BaseAgent
from agentmesh.agents.worker import AssignmentWorker
from agentmesh.clients.mcp_client import MCPClient
from agentmesh.config import Settings, get_settings
from agentmesh.storage.resources import PostgresResourceRepository

AgentFactory = Callable[[Settings], tuple[BaseAgent, Callable[[], None]]]


def run_agent_cli(agent_factory: AgentFactory, *, description: str) -> None:
    """Run one agent standalone or as an AgentMesh polling worker."""

    parser = argparse.ArgumentParser(description=description)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt", help="Run one standalone LLM task and print the result.")
    mode.add_argument("--worker", action="store_true", help="Poll AgentMesh for assignments.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="In worker mode, process at most one assignment and exit.",
    )
    parser.add_argument(
        "--api-url",
        help="Override AGENTMESH_API_URL for this worker process.",
    )
    args = parser.parse_args()
    settings = get_settings()
    agent, close_agent = agent_factory(settings)
    try:
        if args.prompt is not None:
            result = agent.run_task({"messages": [args.prompt]})
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return

        client = MCPClient(
            args.api_url or settings.agentmesh_api_url,
            timeout_seconds=settings.worker_request_timeout_seconds,
        )
        try:
            resource_repository = PostgresResourceRepository.from_connection_url(
                settings.database_url
            )
            worker = AssignmentWorker(
                agent,
                client,
                poll_interval_seconds=settings.poll_interval_seconds,
                heartbeat_seconds=settings.worker_heartbeat_seconds,
                resource_repository=resource_repository,
            )
            if args.once:
                print(json.dumps({"processed": worker.run_once(), "agent": agent.agent_name}))
            else:
                worker.run_forever()
        finally:
            if "resource_repository" in locals():
                resource_repository.close()
            client.close()
    finally:
        close_agent()
