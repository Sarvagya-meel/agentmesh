from agentmesh.agents.common.contracts.agent_card import AgentCard
from agentmesh.services.agentmesh_server.registry.repository import InMemoryRegistryRepository
from agentmesh.services.agentmesh_server.registry.service import RegistryService


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
    assert refreshed.last_seen is not None
