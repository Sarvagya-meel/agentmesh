from datetime import UTC, datetime, timedelta

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
