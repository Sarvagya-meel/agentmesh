from datetime import UTC, datetime, timedelta
from typing import Any

from agentmesh.core.models.agent_card import AgentCard
from agentmesh.services.service_agentmesh_server.registry.repository import (
    InMemoryRegistryRepository,
)
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService


def test_agent_registration_and_capability_lookup() -> None:
    repository = InMemoryRegistryRepository()
    service = RegistryService(repository)

    card = AgentCard(
        agent_id="langgraph-copilot",
        name="langgraph-copilot",
        description="Handles chat replies with human approval",
        capabilities=["CHAT", "REVIEW"],
        skills=["conversation"],
        endpoint="http://localhost:8001",
    )

    registered = service.register_agent(card)
    assert registered.agent_id == "langgraph-copilot"
    assert service.get_agent("langgraph-copilot") == registered
    assert service.find_capable_agents("CHAT")[0].agent_id == "langgraph-copilot"


def test_agent_heartbeat_marks_agent_online() -> None:
    service = RegistryService(InMemoryRegistryRepository())
    card = AgentCard(
        agent_id="job-detector",
        name="job_detector",
        capabilities=["JOB_DETECT"],
        endpoint="http://localhost:8002",
        status="offline",
    )

    service.register_agent(card)
    refreshed = service.heartbeat("job-detector")

    assert refreshed.status == "online"


def test_agent_heartbeat_records_runtime_telemetry() -> None:
    service = RegistryService(InMemoryRegistryRepository())
    service.register_agent(
        AgentCard(agent_id="telemetry-agent", name="telemetry-agent", status="starting")
    )

    refreshed = service.heartbeat(
        "telemetry-agent",
        {
            "runtime_instance_id": "runtime-1",
            "runtime_status": "READY",
            "active_task_count": 1,
        },
    )

    assert refreshed.status == "online"
    assert refreshed.metadata["runtime_instance_id"] == "runtime-1"
    assert refreshed.metadata["active_task_count"] == 1
    assert refreshed.last_seen is not None


def test_listing_agents_marks_expired_presence_stale() -> None:
    repository = InMemoryRegistryRepository()
    service = RegistryService(repository, stale_seconds=180)
    repository.register(
        AgentCard(
            agent_id="expired-agent",
            name="expired-agent",
            status="online",
            last_seen=datetime.now(UTC) - timedelta(seconds=181),
        )
    )

    listed = service.list_agents()

    assert listed[0].status == "stale"
    assert repository.get("expired-agent").status == "stale"


def test_multi_instance_agent_uses_ready_runtime_last_seen() -> None:
    class FakeResourceRepository:
        def mark_stale_runtime_instances(self, *, stale_seconds: float) -> list[str]:
            return []

        def runtime_availability(self, agent_id: str, *, stale_seconds: float) -> dict[str, Any]:
            return {
                "direct_ready": True,
                "assignment_ready": True,
                "ready_runtime_count": 1,
                "ready_runtime_roles": ["combined"],
                "direct_endpoint": "http://runtime:8101",
                "last_seen": runtime_last_seen,
            }

    runtime_last_seen = datetime.now(UTC)
    parent_last_seen = runtime_last_seen - timedelta(minutes=10)
    repository = InMemoryRegistryRepository()
    repository.register(
        AgentCard(
            agent_id="langgraph-copilot",
            name="langgraph-copilot",
            status="online",
            endpoint="http://parent:8101",
            metadata={"runtime_model": "multi-instance"},
            last_seen=parent_last_seen,
        )
    )
    service = RegistryService(
        repository,
        stale_seconds=180,
        resource_repository=FakeResourceRepository(),
    )

    listed = service.list_agents()

    assert listed[0].status == "online"
    assert listed[0].endpoint == "http://runtime:8101"
    assert listed[0].last_seen == runtime_last_seen
    assert repository.get("langgraph-copilot").last_seen == runtime_last_seen
