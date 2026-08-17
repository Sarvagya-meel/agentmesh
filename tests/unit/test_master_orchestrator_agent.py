from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from agentmesh.agents.agent_langgraph_orchestrator_supervisor import MasterOrchestratorAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.core.agent_card import AgentCard
from agentmesh.services.service_agentmesh_server.database.repository import InMemoryEventRepository
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.repository import (
    InMemoryRegistryRepository,
)
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService


def build_master_agent() -> tuple[MasterOrchestratorAgent, EventService]:
    registry = RegistryService(InMemoryRegistryRepository())
    registry.register_agent(
        AgentCard(
            agent_id="research-agent",
            name="research-agent",
            capabilities=["RESEARCH"],
        )
    )
    registry.register_agent(
        AgentCard(
            agent_id="review-agent",
            name="review-agent",
            capabilities=["REVIEW"],
        )
    )
    event_service = EventService(InMemoryEventRepository())
    state_service = StateService(event_service)
    return (
        MasterOrchestratorAgent(
            registry_service=registry,
            event_service=event_service,
            state_service=state_service,
        ),
        event_service,
    )


def test_master_agent_requires_only_plan_approval_before_dispatch() -> None:
    master, event_service = build_master_agent()

    started = master.start_workflow(
        "conversation-1",
        "Research and review an architecture proposal",
        preferred_agent_ids=["research-agent", "review-agent"],
    )
    workflow_id = UUID(started["workflow_id"])

    assert started["status"] == "AWAITING_PLAN_APPROVAL"
    assert started["pending_input"]["type"] == "human_approval"
    assert [option["value"] for option in started["pending_input"]["options"]] == [
        "APPROVE",
        "REVISE",
        "REJECT",
    ]
    assert "TASK_ASSIGNED" not in [event.event_type for event in event_service.replay(workflow_id)]

    plan_approved = master.submit_human_decision(workflow_id, decision="APPROVE")
    assert plan_approved["status"] == "WAITING_FOR_AGENT"
    assigned_events = [
        event for event in event_service.replay(workflow_id) if event.event_type == "TASK_ASSIGNED"
    ]
    assert len(assigned_events) == 1
    assert assigned_events[0].target_agent == "research-agent"
    assert "TASK_APPROVAL_REQUESTED" not in [
        event.event_type for event in event_service.replay(workflow_id)
    ]


def test_master_agent_uses_the_shared_agent_contract() -> None:
    master, _event_service = build_master_agent()

    assert isinstance(master, BaseAgent)
    assert master.agent_card().agent_id == "orchestrator-supervisor-agent"
    assert "ORCHESTRATE" in master.agent_card().capabilities

    started = master.run_task(
        {
            "conversation_id": "conversation-agent-contract",
            "goal": "Research an architecture proposal",
            "preferred_agent_ids": ["research-agent"],
        }
    )

    assert started["status"] == "AWAITING_PLAN_APPROVAL"


def test_master_agent_completes_all_approved_tasks() -> None:
    master, event_service = build_master_agent()
    started = master.start_workflow(
        "conversation-2",
        "Research and review an architecture proposal",
        preferred_agent_ids=["research-agent", "review-agent"],
    )
    workflow_id = UUID(started["workflow_id"])

    first_assignment = master.submit_human_decision(workflow_id, decision="APPROVE")
    first_task_id = UUID(first_assignment["current_task"]["task_id"])
    second_assignment = master.submit_task_result(
        workflow_id,
        task_id=first_task_id,
        status="COMPLETED",
        result={"findings": ["event sourcing"]},
    )

    assert second_assignment["status"] == "WAITING_FOR_AGENT"
    second_task_id = UUID(second_assignment["current_task"]["task_id"])
    completed = master.submit_task_result(
        workflow_id,
        task_id=second_task_id,
        status="COMPLETED",
        result={"approved": True},
    )

    assert completed["status"] == "COMPLETED"
    event_types = [event.event_type for event in event_service.replay(workflow_id)]
    assert event_types.count("TASK_ASSIGNED") == 2
    assert event_types[-1] == "WORKFLOW_COMPLETED"


def test_plan_revision_creates_a_new_version_and_requests_approval_again() -> None:
    master, event_service = build_master_agent()
    started = master.start_workflow(
        "conversation-3",
        "Research an architecture proposal",
        preferred_agent_ids=["research-agent"],
    )
    workflow_id = UUID(started["workflow_id"])

    revised = master.submit_human_decision(
        workflow_id,
        decision="REVISE",
        feedback="Include a security review.",
    )

    assert revised["status"] == "AWAITING_PLAN_APPROVAL"
    assert revised["plan"]["version"] == 2
    assert "security review" in revised["plan"]["tasks"][0]["description"].lower()
    event_types = [event.event_type for event in event_service.replay(workflow_id)]
    assert event_types.count("PLAN_CREATED") == 2
    assert "PLAN_REVISION_REQUESTED" in event_types


def test_rejected_plan_cancels_without_dispatching_tasks() -> None:
    master, event_service = build_master_agent()
    started = master.start_workflow(
        "conversation-4",
        "Research an architecture proposal",
        preferred_agent_ids=["research-agent"],
    )
    workflow_id = UUID(started["workflow_id"])

    cancelled = master.submit_human_decision(workflow_id, decision="REJECT")

    assert cancelled["status"] == "CANCELLED"
    event_types = [event.event_type for event in event_service.replay(workflow_id)]
    assert "WORKFLOW_CANCELLED" in event_types
    assert "TASK_ASSIGNED" not in event_types


def test_master_agent_excludes_stale_workers_from_discovery() -> None:
    repository = InMemoryRegistryRepository()
    registry = RegistryService(repository)
    registry.register_agent(
        AgentCard(agent_id="fresh-agent", name="fresh-agent", capabilities=["REVIEW"])
    )
    repository.register(
        AgentCard(
            agent_id="stale-agent",
            name="stale-agent",
            capabilities=["REVIEW"],
            last_seen=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    event_service = EventService(InMemoryEventRepository())
    master = MasterOrchestratorAgent(
        registry_service=registry,
        event_service=event_service,
        state_service=StateService(event_service),
        agent_stale_seconds=180,
    )

    workflow_id = uuid4()
    master.start_workflow(
        "conversation-stale-agent",
        "Review this proposal",
        workflow_id=workflow_id,
    )

    snapshot_event = next(
        event
        for event in event_service.replay(workflow_id)
        if event.event_type == "AGENT_SNAPSHOT_CAPTURED"
    )
    discovered_ids = {card["agent_id"] for card in snapshot_event.payload["agents"]}
    assert discovered_ids == {"fresh-agent"}
