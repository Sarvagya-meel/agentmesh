from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.core.models.agent_card import AgentCard
from agentmesh.services.service_agentmesh_server.api.dependencies import get_registry_service
from agentmesh.services.service_agentmesh_server.api.schemas import AgentHeartbeatRequest
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService

router = APIRouter(prefix="/registry", tags=["registry"])


@router.post("/agents", status_code=201)
def register_agent(
    card: AgentCard,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentCard:
    return service.register_agent(card)


@router.put("/agents/{agent_id}")
def upsert_agent(
    agent_id: str,
    card: AgentCard,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentCard:
    if card.agent_id != agent_id:
        raise HTTPException(status_code=400, detail="Path agent_id must match agent card.")
    return service.upsert_agent(card)


@router.get("/agents")
def list_agents(
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> list[AgentCard]:
    return service.list_agents()


@router.get("/agents/{agent_id}")
def get_agent(
    agent_id: str,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentCard:
    card = service.get_agent(agent_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id!r} not found.")
    return card


@router.post("/agents/{agent_id}/heartbeat")
def heartbeat(
    agent_id: str,
    body: AgentHeartbeatRequest,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> AgentCard:
    if body.agent_id != agent_id:
        raise HTTPException(status_code=400, detail="Path agent_id must match heartbeat agent_id.")
    return service.heartbeat(agent_id, body.model_dump(exclude_none=True))


@router.get("/agents/capabilities/{capability}")
def find_by_capability(
    capability: str,
    service: Annotated[RegistryService, Depends(get_registry_service)],
) -> list[AgentCard]:
    return service.find_capable_agents(capability)
