from __future__ import annotations

from typing import cast

from fastapi import Request

from agentmesh.orchestration.master_agent import MasterOrchestratorAgent
from agentmesh.registry.service import RegistryService
from agentmesh.services.event_service import EventService
from agentmesh.services.state_service import StateService
from agentmesh.services.worker_service import WorkerService


def get_registry_service(request: Request) -> RegistryService:
    return cast(RegistryService, request.app.state.registry_service)


def get_event_service(request: Request) -> EventService:
    return cast(EventService, request.app.state.event_service)


def get_state_service(request: Request) -> StateService:
    return cast(StateService, request.app.state.state_service)


def get_master_orchestrator(request: Request) -> MasterOrchestratorAgent:
    return cast(MasterOrchestratorAgent, request.app.state.master_orchestrator)


def get_worker_service(request: Request) -> WorkerService:
    return cast(WorkerService, request.app.state.worker_service)
