from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agentmesh.registry.models import AgentCard
from agentmesh.registry.repository import InMemoryRegistryRepository
from agentmesh.registry.service import RegistryService

router = APIRouter(prefix="/registry", tags=["registry"])
_registry_service = RegistryService(InMemoryRegistryRepository())


@router.post("/agents", status_code=201)
def register_agent(card: AgentCard) -> AgentCard:
    return _registry_service.register_agent(card)


@router.get("/agents")
def list_agents() -> list[AgentCard]:
    return _registry_service.list_agents()


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> AgentCard:
    card = _registry_service.get_agent(agent_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id!r} not found.")
    return card


@router.post("/agents/{agent_id}/heartbeat")
def heartbeat(agent_id: str) -> AgentCard:
    return _registry_service.heartbeat(agent_id)


@router.get("/agents/capabilities/{capability}")
def find_by_capability(capability: str) -> list[AgentCard]:
    return _registry_service.find_capable_agents(capability)
