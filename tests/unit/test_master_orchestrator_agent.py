from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from agentmesh.agents.agent_langgraph_orchestrator_supervisor import MasterOrchestratorAgent
from agentmesh.agents.agent_langgraph_orchestrator_supervisor.agent import merge_task_results
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.execution import ExecutionContext
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.services.service_agentmesh_server.database.repository import InMemoryEventRepository
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.repository import (
    InMemoryRegistryRepository,
)
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService


def build_master_agent(
    *,
    store: BaseStore | None = None,
    long_term_memory_enabled: bool = False,
) -> tuple[MasterOrchestratorAgent, EventService]:
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
            store=store,
            long_term_memory_enabled=long_term_memory_enabled,
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


def test_agent_output_approval_resumes_the_same_agent_thread() -> None:
    master, event_service = build_master_agent()
    started = master.start_workflow(
        "conversation-agent-approval",
        "Review an architecture proposal",
        preferred_agent_ids=["review-agent"],
    )
    workflow_id = UUID(started["workflow_id"])
    assignment = master.submit_human_decision(workflow_id, decision="APPROVE")
    task_id = UUID(assignment["current_task"]["task_id"])

    waiting = master.submit_task_result(
        workflow_id,
        task_id=task_id,
        status="AWAITING_APPROVAL",
        result={
            "status": "AWAITING_APPROVAL",
            "thread_id": "agent-thread-1",
            "draft_reply": "Draft architecture review",
        },
    )

    assert waiting["status"] == "AWAITING_AGENT_APPROVAL"
    assert waiting["pending_input"]["approval"]["approval_type"] == "AGENT_OUTPUT"
    assert waiting["pending_input"]["draft_reply"] == "Draft architecture review"

    resumed = master.submit_human_decision(
        workflow_id,
        decision="REVISE",
        feedback="Include security controls.",
    )

    assert resumed["status"] == "WAITING_FOR_AGENT"
    payload = resumed["current_task"]["payload"]
    assert payload["resume_thread_id"] == "agent-thread-1"
    assert payload["approval_decision"] == "revise"
    assert payload["approval_feedback"] == "Include security controls."
    event_types = [event.event_type for event in event_service.replay(workflow_id)]
    assert "AGENT_OUTPUT_PROPOSED" in event_types
    assert "AGENT_APPROVAL_REQUESTED" in event_types
    assert "AGENT_OUTPUT_REVISION_REQUESTED" in event_types


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


def test_rerun_workflow_creates_linked_execution_without_overwriting_original() -> None:
    master, event_service = build_master_agent()
    original = master.start_workflow(
        "conversation-rerun",
        "Review an architecture proposal",
        preferred_agent_ids=["review-agent"],
    )
    original_id = UUID(original["workflow_id"])

    rerun = master.rerun_workflow(original_id)

    rerun_id = UUID(rerun["workflow_id"])
    assert rerun_id != original_id
    assert rerun["status"] == "AWAITING_PLAN_APPROVAL"
    assert rerun["rerun_of_workflow_id"] == str(original_id)
    original_event_types = [event.event_type for event in event_service.replay(original_id)]
    assert "WORKFLOW_RERUN_REQUESTED" in original_event_types


def test_rerun_task_links_new_execution_to_workflow_and_task() -> None:
    master, event_service = build_master_agent()
    original = master.start_workflow(
        "conversation-task-rerun",
        "Research an architecture proposal",
        preferred_agent_ids=["research-agent"],
    )
    original_id = UUID(original["workflow_id"])
    task_id = UUID(original["plan"]["tasks"][0]["task_id"])

    rerun = master.rerun_task(original_id, task_id)

    assert rerun["rerun_of_workflow_id"] == str(original_id)
    assert rerun["rerun_of_task_id"] == str(task_id)
    rerun_event = next(
        event
        for event in event_service.replay(original_id)
        if event.event_type == "TASK_RERUN_REQUESTED"
    )
    assert rerun_event.payload["task_id"] == str(task_id)


def test_task_result_reducer_is_order_independent_and_idempotent() -> None:
    first = {"task_id": "task-b", "attempt_number": 1, "result": {"value": "B"}}
    second = {"task_id": "task-a", "attempt_number": 2, "result": {"value": "A"}}

    forward = merge_task_results([first], [second, first])
    reverse = merge_task_results([second], [first])

    assert forward == reverse
    assert forward == [second, first]


async def test_supervisor_has_native_async_entry_and_mermaid_export() -> None:
    master, _ = build_master_agent()

    started = await master.arun_task(
        {
            "conversation_id": "async-supervisor",
            "goal": "Review an architecture proposal",
            "preferred_agent_ids": ["review-agent"],
        }
    )

    assert started["status"] == "AWAITING_PLAN_APPROVAL"
    mermaid = master.graph_mermaid()
    for node in master.graph.nodes:
        assert node in mermaid


async def test_supervisor_memory_is_opt_in_namespaced_and_deletable() -> None:
    master, _ = build_master_agent(
        store=InMemoryStore(),
        long_term_memory_enabled=True,
    )
    alice = await master.arun_task(
        {
            "conversation_id": "memory-alice-one",
            "goal": "Plan a concise architecture review",
            "preferred_agent_ids": ["review-agent"],
            "memory_user_id": "alice",
            "memory_opt_in": True,
            "memory_updates": {"response_style": "concise"},
        }
    )
    alice_again = await master.arun_task(
        {
            "conversation_id": "memory-alice-two",
            "goal": "Plan another architecture review",
            "preferred_agent_ids": ["review-agent"],
            "memory_user_id": "alice",
            "memory_opt_in": True,
        }
    )
    bob = await master.arun_task(
        {
            "conversation_id": "memory-bob",
            "goal": "Plan an architecture review",
            "preferred_agent_ids": ["review-agent"],
            "memory_user_id": "bob",
            "memory_opt_in": True,
        }
    )

    assert (
        alice["plan"]["tasks"][0]["payload"]["approved_user_preferences"][0]["value"] == "concise"
    )
    assert (
        alice_again["plan"]["tasks"][0]["payload"]["approved_user_preferences"][0]["value"]
        == "concise"
    )
    assert bob["plan"]["tasks"][0]["payload"]["approved_user_preferences"] == []

    deleted = await master.arun_task(
        {
            "conversation_id": "memory-alice-delete",
            "goal": "Plan a final architecture review",
            "preferred_agent_ids": ["review-agent"],
            "memory_user_id": "alice",
            "memory_opt_in": True,
            "memory_delete_keys": ["response_style"],
        }
    )
    assert deleted["plan"]["tasks"][0]["payload"]["approved_user_preferences"] == []

    with pytest.raises(ValidationError, match="Credential-like"):
        await master.arun_task(
            {
                "conversation_id": "memory-secret",
                "goal": "Plan an architecture review",
                "preferred_agent_ids": ["review-agent"],
                "memory_user_id": "alice",
                "memory_opt_in": True,
                "memory_updates": {"note": "sk-not-a-real-key"},
            }
        )


async def test_supervisor_replay_and_fork_do_not_mutate_source() -> None:
    master, event_service = build_master_agent()
    started = await master.astart_workflow(
        "checkpoint-source",
        "Review an architecture proposal",
        preferred_agent_ids=["review-agent"],
    )
    workflow_id = UUID(started["workflow_id"])
    history = await master.checkpoint_history(workflow_id)
    checkpoint_id = str(history[0]["checkpoint_id"])
    source_before = await master.graph.aget_state(master._config(workflow_id))
    source_event_count = len(event_service.replay(workflow_id))

    replay = await master.replay_checkpoint(workflow_id, checkpoint_id)
    fork_workflow_id = uuid4()
    fork = await master.fork_checkpoint(
        workflow_id,
        checkpoint_id,
        new_workflow_id=fork_workflow_id,
        state_updates={"feedback": "Diagnostic fork"},
    )
    source_after = await master.graph.aget_state(master._config(workflow_id))
    fork_state = await master.graph.aget_state(master._config(fork_workflow_id))

    assert replay["mode"] == "read_only_replay"
    assert fork["mode"] == "diagnostic_fork"
    assert fork_state.values["workflow_id"] == str(fork_workflow_id)
    assert fork_state.values["feedback"] == "Diagnostic fork"
    assert source_after.config == source_before.config
    assert source_after.values == source_before.values
    assert len(event_service.replay(workflow_id)) == source_event_count


async def test_supervisor_checkpoints_capture_execution_metadata() -> None:
    master, _ = build_master_agent()
    workflow_id = uuid4()
    context = ExecutionContext(
        source="queued",
        workflow_id=str(workflow_id),
        assignment_id="assignment-1",
        attempt_number=2,
        run_id="run-1",
    )

    await master.arun_task(
        {
            "workflow_id": str(workflow_id),
            "conversation_id": "trace-context",
            "goal": "Review an architecture proposal",
            "preferred_agent_ids": ["review-agent"],
            "task_id": "task-1",
        },
        context,
    )
    history = await master.checkpoint_history(workflow_id)

    assert any(
        snapshot["metadata"].get("run_id") == "run-1"
        and snapshot["metadata"].get("assignment_id") == "assignment-1"
        and snapshot["metadata"].get("task_id") == "task-1"
        and snapshot["metadata"].get("attempt_number") == 2
        for snapshot in history
    )
