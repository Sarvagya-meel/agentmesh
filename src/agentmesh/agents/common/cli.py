from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.control_plane_client import AsyncControlPlaneClient
from agentmesh.agents.common.execution import AgentExecutor
from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.agents.common.worker import AssignmentWorker
from agentmesh.config import Settings, get_settings

Cleanup = Callable[[], None | Awaitable[None]]
FactoryResult = tuple[BaseAgent, Cleanup]
AgentFactory = Callable[[Settings], FactoryResult | Awaitable[FactoryResult]]


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
    asyncio.run(_run_cli(args, agent_factory))


async def _run_cli(args: argparse.Namespace, agent_factory: AgentFactory) -> None:
    settings = get_settings()
    factory_result = agent_factory(settings)
    if inspect.isawaitable(factory_result):
        factory_result = await factory_result
    agent, close_agent = factory_result
    try:
        if args.prompt is not None:
            result = await agent.arun_task({"messages": [args.prompt]})
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return

        await _run_worker(
            agent,
            settings,
            api_url=args.api_url,
            once=args.once,
        )
    finally:
        cleanup_result = close_agent()
        if inspect.isawaitable(cleanup_result):
            await cleanup_result


async def _run_worker(
    agent: BaseAgent,
    settings: Settings,
    *,
    api_url: str | None,
    once: bool,
) -> None:
    client = AsyncControlPlaneClient(
        api_url or settings.agentmesh_api_url,
        timeout_seconds=settings.worker_request_timeout_seconds,
    )
    resource_repository = PostgresResourceRepository.from_connection_url(settings.database_url)
    worker = AssignmentWorker(
        AgentExecutor(agent, max_concurrency=settings.agent_max_concurrency),
        client,
        runtime_role="worker",
        poll_interval_seconds=settings.poll_interval_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        resource_repository=resource_repository,
        max_concurrency=settings.agent_max_concurrency,
    )
    try:
        await worker.start()
        if once:
            processed = await worker.run_once()
            print(json.dumps({"processed": processed, "agent": agent.agent_name}))
            return
        stop_event = asyncio.Event()
        try:
            await worker.run_forever(stop_event)
        except KeyboardInterrupt:
            stop_event.set()
    finally:
        await worker.stop()
        resource_repository.close()
        await client.close()
