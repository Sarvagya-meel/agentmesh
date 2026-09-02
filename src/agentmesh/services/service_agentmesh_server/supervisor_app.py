from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentmesh.agents.agent_langgraph_orchestrator_supervisor import MasterOrchestratorAgent
from agentmesh.agents.agent_langgraph_orchestrator_supervisor.factory import (
    create_workflow_planner,
)
from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.config import get_settings
from agentmesh.core.frameworks.langgraph import (
    create_async_langgraph_checkpointer,
    create_langgraph_store,
)
from agentmesh.core.models.exceptions import AgentMeshError, ModelProviderError
from agentmesh.core.observability import configure_langsmith
from agentmesh.services.service_agentmesh_server.api.routes import workflows
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService
from agentmesh.services.service_agentmesh_server.supervisor.client import (
    ControlPlaneGateway,
    RemoteEventService,
    RemoteRegistryService,
    RemoteStateService,
)
from agentmesh.services.service_agentmesh_server.supervisor.runner import (
    SupervisorActionRunner,
)


async def _heartbeat_loop(
    gateway: ControlPlaneGateway,
    orchestrator: MasterOrchestratorAgent,
    *,
    runtime_instance_id: str,
    interval_seconds: float,
    resource_repository: PostgresResourceRepository | None = None,
) -> None:
    while True:
        try:
            await asyncio.to_thread(
                gateway.heartbeat,
                orchestrator.agent_card(),
                runtime_instance_id=runtime_instance_id,
            )
            await _upsert_supervisor_resource(
                orchestrator,
                runtime_instance_id=runtime_instance_id,
                status="ready",
                resource_repository=resource_repository,
                trace=False,
            )
        except (httpx.HTTPError, OSError):
            pass
        await asyncio.sleep(interval_seconds)


async def _upsert_supervisor_resource(
    orchestrator: MasterOrchestratorAgent,
    *,
    runtime_instance_id: str,
    status: str,
    resource_repository: PostgresResourceRepository | None,
    trace: bool = True,
) -> None:
    if resource_repository is None:
        return
    card = orchestrator.agent_card()
    runtime_resource_id = f"orchestrator:{card.agent_id}:runtime:{runtime_instance_id}"
    telemetry = {
        "agent_id": card.agent_id,
        "agent_version": card.version,
        "runtime_instance_id": runtime_instance_id,
        "runtime_role": "supervisor",
        "runtime_status": status.upper(),
        "endpoint": card.endpoint,
        "active_task_count": 0,
        "started_at": datetime.now(UTC).isoformat(),
    }
    await asyncio.to_thread(
        resource_repository.upsert_resource,
        card.agent_id,
        resource_type="orchestrator",
        name=card.name,
        status="online" if status in {"ready", "online"} else status,
        endpoint=card.endpoint,
        owner=card.owner,
        capabilities=card.capabilities,
        metadata={"runtime_model": "multi-instance", **card.metadata},
        trace=trace,
    )
    await asyncio.to_thread(
        resource_repository.upsert_resource,
        runtime_resource_id,
        resource_type="agent_runtime",
        name=f"{card.agent_id}-supervisor",
        status=status,
        endpoint=card.endpoint,
        owner=card.owner,
        capabilities=card.capabilities,
        metadata=telemetry,
        parent_resource_id=card.agent_id,
        trace=trace,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_langsmith(settings)
    token = (
        settings.internal_service_token.get_secret_value()
        if settings.internal_service_token is not None
        else ""
    )
    gateway = ControlPlaneGateway(
        settings.agentmesh_api_url,
        timeout_seconds=settings.worker_request_timeout_seconds,
        service_token=token,
    )
    event_service = RemoteEventService(gateway)
    state_service = RemoteStateService(gateway)
    registry_service = RemoteRegistryService(gateway)
    checkpointer, close_checkpointer = await create_async_langgraph_checkpointer(settings)
    store, close_store = create_langgraph_store(settings)
    planner, close_planner = create_workflow_planner(settings)
    resource_repository = (
        PostgresResourceRepository.from_connection_url(settings.database_url)
        if settings.registry_backend.strip().lower() == "postgres"
        else None
    )
    orchestrator = MasterOrchestratorAgent(
        registry_service=cast(RegistryService, registry_service),
        event_service=cast(EventService, event_service),
        state_service=cast(StateService, state_service),
        planner=planner,
        checkpointer=checkpointer,
        store=store,
        agent_stale_seconds=settings.agent_stale_seconds,
        long_term_memory_enabled=settings.langgraph_long_term_memory_enabled,
        memory_retention_days=settings.langgraph_memory_retention_days,
        endpoint=settings.supervisor_api_url,
    )
    runtime_instance_id = f"{socket.gethostname()}-{uuid4()}"
    await asyncio.to_thread(gateway.register, orchestrator.agent_card())
    await _upsert_supervisor_resource(
        orchestrator,
        runtime_instance_id=runtime_instance_id,
        status="ready",
        resource_repository=resource_repository,
    )
    runner = SupervisorActionRunner(
        gateway=gateway,
        orchestrator=orchestrator,
        supervisor_id=settings.supervisor_agent_id,
        worker_id=runtime_instance_id,
        poll_interval_seconds=settings.poll_interval_seconds,
        lease_seconds=settings.supervisor_action_lease_seconds,
    )
    runner_task = asyncio.create_task(runner.run())
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            gateway,
            orchestrator,
            runtime_instance_id=runtime_instance_id,
            interval_seconds=settings.worker_heartbeat_seconds,
            resource_repository=resource_repository,
        )
    )
    app.state.settings = settings
    app.state.master_orchestrator = orchestrator
    app.state.runner = runner
    try:
        yield
    finally:
        runner.stop()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        await runner_task
        close_planner()
        close_store()
        await close_checkpointer()
        if resource_repository is not None:
            await asyncio.to_thread(resource_repository.close)
        gateway.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=f"{settings.app_name} Supervisor", lifespan=lifespan)
    app.include_router(workflows.router)

    @app.exception_handler(ModelProviderError)
    async def model_provider_error_handler(
        _request: Request, exc: ModelProviderError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(AgentMeshError)
    async def agentmesh_error_handler(_request: Request, exc: AgentMeshError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "supervisor"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        return {"status": "ready", "service": "supervisor"}

    return app


app = create_app()
