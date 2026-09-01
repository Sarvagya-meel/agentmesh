from __future__ import annotations

from typing import cast

from fastapi import Request

from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.orchestration import WorkflowOrchestrator
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService
from agentmesh.services.service_agentmesh_server.supervisor.service import SupervisorActionService
from agentmesh.services.service_agentmesh_server.workers.service import WorkerService


def get_registry_service(request: Request) -> RegistryService:
    return cast(RegistryService, request.app.state.registry_service)


def get_event_service(request: Request) -> EventService:
    return cast(EventService, request.app.state.event_service)


def get_state_service(request: Request) -> StateService:
    return cast(StateService, request.app.state.state_service)


def get_master_orchestrator(request: Request) -> WorkflowOrchestrator:
    return cast(WorkflowOrchestrator, request.app.state.master_orchestrator)


def get_worker_service(request: Request) -> WorkerService:
    return cast(WorkerService, request.app.state.worker_service)


def get_supervisor_action_service(request: Request) -> SupervisorActionService:
    return cast(SupervisorActionService, request.app.state.supervisor_action_service)
