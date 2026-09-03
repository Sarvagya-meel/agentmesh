from __future__ import annotations

from uuid import uuid4

import pytest

from agentmesh.core.models import Event, RoutingMode
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import AgentRegistryError
from agentmesh.services.service_agentmesh_server.database.repository import (
    InMemoryClaimRepository,
    InMemoryEventRepository,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.workers.service import WorkerService


class StaleRegisteredRegistry:
    def get_agent(self, agent_id: str) -> AgentCard | None:
        return AgentCard(
            agent_id=agent_id,
            name=agent_id,
            capabilities=["CHAT"],
            status="stale",
            metadata={"runtime_model": "multi-instance", "assignment_ready": False},
        )

    def is_assignment_ready(self, agent_id: str) -> bool:
        return False


def build_worker_service(event_service: EventService) -> WorkerService:
    return WorkerService(
        event_service=event_service,
        claim_repository=InMemoryClaimRepository(),
        registry_service=StaleRegisteredRegistry(),  # type: ignore[arg-type]
        orchestrator=object(),  # type: ignore[arg-type]
        lease_seconds=30,
    )


def test_registered_worker_can_poll_assignments_while_runtime_recovers() -> None:
    event_service = EventService(InMemoryEventRepository())
    service = build_worker_service(event_service)
    workflow_id = uuid4()
    task_id = uuid4()
    assignment = event_service.append(
        Event(
            conversation_id="conversation",
            workflow_id=workflow_id,
            event_type="TASK_ASSIGNED",
            source_agent="agentmesh-control-plane",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="langgraph-copilot",
            payload={
                "task": {
                    "task_id": str(task_id),
                    "workflow_id": str(workflow_id),
                    "description": "recover from degraded runtime",
                }
            },
        )
    )

    assert service.list_assignments("langgraph-copilot") == [assignment]


def test_directed_assignment_still_requires_ready_runtime() -> None:
    event_service = EventService(InMemoryEventRepository())
    service = build_worker_service(event_service)

    with pytest.raises(AgentRegistryError):
        service.submit_directed_assignment(
            "langgraph-copilot",
            message="Do not queue new user work while unavailable.",
        )
