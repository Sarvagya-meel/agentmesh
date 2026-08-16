from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentmesh.api.routes import events, registry, state, workers, workflows
from agentmesh.config import get_settings
from agentmesh.core.exceptions import (
    AgentMeshError,
    ClaimConflictError,
    ModelProviderError,
    WorkflowConflictError,
    WorkflowNotFoundError,
)
from agentmesh.orchestration.checkpoint import create_orchestration_checkpointer
from agentmesh.orchestration.factory import create_workflow_planner
from agentmesh.orchestration.master_agent import MasterOrchestratorAgent
from agentmesh.registry.repository import InMemoryRegistryRepository
from agentmesh.registry.service import RegistryService
from agentmesh.services.event_service import EventService
from agentmesh.services.state_service import StateService
from agentmesh.services.worker_service import WorkerService
from agentmesh.storage.repository import create_claim_repository, create_event_repository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    event_repository, close_event_repository = create_event_repository(settings)
    claim_repository, close_claim_repository = create_claim_repository(settings)
    event_service = EventService(event_repository)
    state_service = StateService(event_service)
    registry_service = RegistryService(InMemoryRegistryRepository())
    checkpointer, close_checkpointer = create_orchestration_checkpointer(settings)
    planner, close_planner = create_workflow_planner(settings)
    app.state.settings = settings
    app.state.event_service = event_service
    app.state.state_service = state_service
    app.state.registry_service = registry_service
    master_orchestrator = MasterOrchestratorAgent(
        registry_service=registry_service,
        event_service=event_service,
        state_service=state_service,
        planner=planner,
        checkpointer=checkpointer,
    )
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
        close_event_repository()
        close_claim_repository()


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
    async def claim_conflict_handler(
        _request: Request, exc: ClaimConflictError
    ) -> JSONResponse:
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
