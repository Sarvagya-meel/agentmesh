from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentmesh.agents.agent_langgraph_orchestrator_supervisor import (
    ORCHESTRATOR_AGENT_ID,
    MasterOrchestratorAgent,
)
from agentmesh.agents.agent_langgraph_orchestrator_supervisor.factory import create_workflow_planner
from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.config import get_settings
from agentmesh.core.database import (
    create_claim_repository,
    create_event_repository,
    create_orchestration_checkpointer,
)
from agentmesh.core.models.exceptions import (
    AgentMeshError,
    ClaimConflictError,
    ModelProviderError,
    WorkflowConflictError,
    WorkflowNotFoundError,
)
from agentmesh.services.service_agentmesh_server.api.routes import (
    events,
    registry,
    state,
    workers,
    workflows,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.repository import (
    create_registry_repository,
)
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService
from agentmesh.services.service_agentmesh_server.workers.service import WorkerService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    event_repository, close_event_repository = create_event_repository(settings)
    claim_repository, close_claim_repository = create_claim_repository(settings)
    registry_repository, close_registry_repository = create_registry_repository(settings)
    event_service = EventService(event_repository)
    state_service = StateService(event_service)
    registry_service = RegistryService(registry_repository)
    checkpointer, close_checkpointer = create_orchestration_checkpointer(settings)
    planner, close_planner = create_workflow_planner(settings)
    resource_repository = (
        PostgresResourceRepository.from_connection_url(settings.database_url)
        if settings.registry_backend.strip().lower() == "postgres"
        else None
    )
    master_orchestrator = MasterOrchestratorAgent(
        registry_service=registry_service,
        event_service=event_service,
        state_service=state_service,
        planner=planner,
        checkpointer=checkpointer,
        agent_stale_seconds=settings.agent_stale_seconds,
        endpoint=settings.agentmesh_api_url,
    )
    register_control_plane_resources(
        master_orchestrator, registry_service, resource_repository
    )
    app.state.settings = settings
    app.state.event_service = event_service
    app.state.state_service = state_service
    app.state.registry_service = registry_service
    app.state.master_orchestrator = master_orchestrator
    app.state.worker_service = WorkerService(
        event_service=event_service,
        claim_repository=claim_repository,
        registry_service=registry_service,
        orchestrator=master_orchestrator,
        lease_seconds=settings.worker_lease_seconds,
    )
    try:
        yield
    finally:
        close_planner()
        close_checkpointer()
        if resource_repository is not None:
            resource_repository.close()
        close_registry_repository()
        close_event_repository()
        close_claim_repository()


def register_control_plane_resources(
    orchestrator: MasterOrchestratorAgent,
    registry_service: RegistryService,
    resource_repository: PostgresResourceRepository | None,
) -> None:
    orchestrator_card = orchestrator.agent_card().model_copy(
        update={"metadata": {"runtime": "fastapi", "resource_type": "orchestrator"}}
    )
    registry_service.upsert_agent(orchestrator_card)
    if resource_repository is None:
        return
    resource_repository.upsert_resource(
        ORCHESTRATOR_AGENT_ID,
        resource_type="orchestrator",
        name=ORCHESTRATOR_AGENT_ID,
        status="online",
        endpoint=orchestrator.endpoint,
        capabilities=orchestrator_card.capabilities,
        metadata={
            "agent_id": ORCHESTRATOR_AGENT_ID,
            "runtime": "fastapi",
            "registry_card": True,
        },
    )
    resource_repository.upsert_resource(
        "agentmesh-registry",
        resource_type="registry",
        name="agentmesh-registry",
        status="online",
        endpoint=f"{orchestrator.endpoint.rstrip('/')}/registry",
        capabilities=["AGENT_DISCOVERY", "AGENT_CARD_LOOKUP", "CAPABILITY_LOOKUP"],
        metadata={
            "mcp_server_candidate": True,
            "future_mcp_tools": [
                "list_agents",
                "get_agent_card",
                "find_agents_by_capability",
                "read_agent_health",
            ],
            "mcp_mutation_policy": "read_first_controlled_writes_later",
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(events.router)
    app.include_router(state.router)
    app.include_router(workflows.router)
    app.include_router(registry.router)
    app.include_router(workers.router)

    @app.exception_handler(WorkflowNotFoundError)
    async def workflow_not_found_handler(
        _request: Request, exc: WorkflowNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(WorkflowConflictError)
    async def workflow_conflict_handler(
        _request: Request, exc: WorkflowConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ClaimConflictError)
    async def claim_conflict_handler(_request: Request, exc: ClaimConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AgentMeshError)
    async def agentmesh_error_handler(_request: Request, exc: AgentMeshError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ModelProviderError)
    async def model_provider_error_handler(
        _request: Request, exc: ModelProviderError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
