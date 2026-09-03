from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from agentmesh.core.models import Event, EventFilters, SupervisorActionType
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.services.service_agentmesh_server.database.repository import (
    InMemoryClaimRepository,
    InMemoryEventRepository,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.supervisor.proxy import (
    QueuedWorkflowOrchestrator,
)
from agentmesh.services.service_agentmesh_server.supervisor.runner import (
    SupervisorActionRunner,
)
from agentmesh.services.service_agentmesh_server.supervisor.service import (
    SupervisorActionService,
)
from agentmesh.services.service_agentmesh_server.supervisor_app import (
    _upsert_supervisor_resource,
)


def build_action_service() -> tuple[SupervisorActionService, EventService]:
    event_service = EventService(InMemoryEventRepository())
    return (
        SupervisorActionService(
            event_service=event_service,
            claim_repository=InMemoryClaimRepository(),
            lease_seconds=30,
        ),
        event_service,
    )


def test_action_is_claimed_and_completed_once() -> None:
    service, event_service = build_action_service()
    workflow_id = uuid4()
    action = service.enqueue(
        conversation_id="conversation",
        workflow_id=workflow_id,
        action_type=SupervisorActionType.START_WORKFLOW,
        arguments={"goal": "test"},
        supervisor_id="supervisor",
    )

    claim = service.claim(action.event_id, supervisor_id="supervisor", worker_id="worker-1")
    terminal = service.complete(
        action.event_id,
        supervisor_id="supervisor",
        worker_id="worker-1",
        claim_token=claim.claim_token,
        result={"status": "ok"},
    )

    assert terminal.event_type == "SUPERVISOR_ACTION_COMPLETED"
    assert service.list_actions("supervisor") == []
    events = event_service.query(EventFilters(workflow_id=workflow_id))
    assert [event.event_type for event in events] == [
        "SUPERVISOR_ACTION_REQUESTED",
        "SUPERVISOR_ACTION_COMPLETED",
    ]


def test_retryable_action_failure_is_not_terminal() -> None:
    service, _ = build_action_service()
    action = service.enqueue(
        conversation_id="conversation",
        workflow_id=uuid4(),
        action_type=SupervisorActionType.START_WORKFLOW,
        arguments={},
        supervisor_id="supervisor",
    )
    claim = service.claim(action.event_id, supervisor_id="supervisor", worker_id="worker-1")

    failed = service.fail(
        action.event_id,
        supervisor_id="supervisor",
        worker_id="worker-1",
        claim_token=claim.claim_token,
        error_code="RateLimitError",
        error_message="rate limit",
        retryable=True,
        retry_after_seconds=0,
    )

    assert failed.event_type == "SUPERVISOR_ACTION_RETRY_SCHEDULED"
    assert service.list_actions("supervisor") == [action]


@pytest.mark.asyncio
async def test_queued_start_is_idempotent_and_projectable() -> None:
    service, event_service = build_action_service()
    proxy = QueuedWorkflowOrchestrator(
        action_service=service,
        state_service=StateService(event_service),
        supervisor_id="supervisor",
        supervisor_api_url="http://supervisor",
    )
    workflow_id = uuid4()

    first = await proxy.astart_workflow("conversation", "goal", workflow_id=workflow_id)
    second = await proxy.astart_workflow("conversation", "goal", workflow_id=workflow_id)

    assert first["status"] == "RUNNING"
    assert second == first
    assert len(service.list_actions("supervisor")) == 1
    events = event_service.replay(workflow_id)
    assert [event.event_type for event in events] == [
        "WORKFLOW_STARTED",
        "SUPERVISOR_ACTION_REQUESTED",
    ]
    assert [event.sequence_number for event in events] == [1, 2]
    assert events[0].source_agent == "agentmesh-control-plane"
    assert events[0].target_agent == "supervisor"
    assert events[0].payload["approval_required"] is True
    assert events[1].payload["arguments"]["start_event_persisted"] is True


@pytest.mark.asyncio
async def test_queued_start_persists_disabled_approval_policy() -> None:
    service, event_service = build_action_service()
    proxy = QueuedWorkflowOrchestrator(
        action_service=service,
        state_service=StateService(event_service),
        supervisor_id="supervisor",
        supervisor_api_url="http://supervisor",
    )

    result = await proxy.astart_workflow("conversation", "goal", approval_required=False)
    events = event_service.replay(UUID(result["workflow_id"]))

    assert events[0].payload["approval_required"] is False
    assert events[1].payload["arguments"]["approval_required"] is False


@pytest.mark.parametrize("task_only", [False, True])
async def test_rerun_returns_new_durable_identity_and_keeps_approval_policy(task_only):
    service, events = build_action_service()
    proxy = QueuedWorkflowOrchestrator(
        action_service=service,
        state_service=StateService(events),
        supervisor_id="supervisor",
        supervisor_api_url="http://supervisor",
    )
    source, task_id = uuid4(), uuid4()
    await proxy.astart_workflow(
        "conversation", "Original goal", workflow_id=source, approval_required=False
    )
    events.append(
        Event(
            conversation_id="conversation",
            workflow_id=source,
            event_type="PLAN_CREATED",
            source_agent="supervisor",
            payload={
                "plan": {
                    "tasks": [
                        {"task_id": str(task_id), "agent_id": "worker", "description": "Task goal"}
                    ]
                }
            },
        )
    )
    previous = events.replay(source)
    children = []
    for _ in range(2):
        result = (
            await proxy.arerun_task(source, task_id)
            if task_only
            else await proxy.arerun_workflow(source)
        )
        child = UUID(result["workflow_id"])
        children.append(child)
        assert child != source
        assert result["rerun_of_workflow_id"] == str(source)
        assert result["rerun_of_task_id"] == (str(task_id) if task_only else None)
        history = events.replay(child)
        assert [event.event_type for event in history] == [
            "WORKFLOW_STARTED",
            "SUPERVISOR_ACTION_REQUESTED",
        ]
        assert history[0].payload["approval_required"] is False
        assert history[1].payload["arguments"]["preferred_agent_ids"] == ["worker"]
        assert history[1].payload["arguments"]["approval_required"] is False
    assert children[0] != children[1]
    assert events.replay(source)[: len(previous)] == previous


async def test_terminal_checkpoint_recovery_is_rejected_before_child_events(monkeypatch):
    service, events = build_action_service()
    proxy = QueuedWorkflowOrchestrator(
        action_service=service,
        state_service=StateService(events),
        supervisor_id="supervisor",
        supervisor_api_url="http://supervisor",
    )
    source, child = uuid4(), uuid4()
    await proxy.astart_workflow("conversation", "Goal", workflow_id=source)

    async def replay(*args):
        return {"next": [], "mode": "read_only_replay"}

    monkeypatch.setattr(proxy, "replay_checkpoint", replay)
    with pytest.raises(ValidationError, match="terminal"):
        await proxy.arecover_checkpoint(source, checkpoint_id="terminal", new_workflow_id=child)
    assert events.replay(child) == []


async def test_rerun_rejects_foreign_task_before_enqueuing():
    service, events = build_action_service()
    proxy = QueuedWorkflowOrchestrator(
        action_service=service,
        state_service=StateService(events),
        supervisor_id="supervisor",
        supervisor_api_url="http://supervisor",
    )
    source = uuid4()
    await proxy.astart_workflow("conversation", "Goal", workflow_id=source)
    previous = events.replay(source)
    with pytest.raises(ValidationError, match="does not belong"):
        await proxy.arerun_task(source, uuid4())
    assert events.replay(source) == previous


@pytest.mark.asyncio
async def test_duplicate_approval_after_state_advance_does_not_enqueue_dead_letter() -> None:
    service, event_service = build_action_service()
    proxy = QueuedWorkflowOrchestrator(
        action_service=service,
        state_service=StateService(event_service),
        supervisor_id="supervisor",
        supervisor_api_url="http://supervisor",
    )
    workflow_id = uuid4()
    event_service.append(
        Event(
            conversation_id="conversation",
            workflow_id=workflow_id,
            event_type="WORKFLOW_STARTED",
            source_agent="supervisor",
            payload={"goal": "goal"},
        )
    )

    result = await proxy.asubmit_human_decision(workflow_id, decision="APPROVE")

    assert result["status"] == "RUNNING"
    assert service.list_actions("supervisor") == []


def test_rate_limit_is_classified_for_control_plane_retry() -> None:
    retryable, delay = SupervisorActionRunner.classify_failure(
        RuntimeError("provider rate limit reached"), 2
    )

    assert retryable is True
    assert delay == 4.0


def test_start_action_uses_workflow_uuid() -> None:
    service, _ = build_action_service()
    workflow_id = uuid4()
    action = service.enqueue(
        conversation_id="conversation",
        workflow_id=workflow_id,
        action_type=SupervisorActionType.START_WORKFLOW,
        arguments={"workflow_id": str(workflow_id)},
        supervisor_id="supervisor",
    )

    assert UUID(str(action.workflow_id)) == workflow_id


@pytest.mark.asyncio
async def test_supervisor_is_written_to_resource_inventory() -> None:
    calls: list[dict[str, object]] = []

    class FakeOrchestrator:
        def agent_card(self) -> AgentCard:
            return AgentCard(
                agent_id="orchestrator-supervisor-agent",
                name="orchestrator-supervisor-agent",
                endpoint="http://supervisor:8110",
                capabilities=["ORCHESTRATE", "PLAN"],
            )

    class FakeResourceRepository:
        def upsert_resource(self, resource_id: str, **kwargs: object) -> None:
            calls.append({"resource_id": resource_id, **kwargs})

    await _upsert_supervisor_resource(
        FakeOrchestrator(),
        runtime_instance_id="runtime-1",
        status="ready",
        resource_repository=FakeResourceRepository(),
        trace=False,
    )

    assert calls[0]["resource_id"] == "orchestrator-supervisor-agent"
    assert calls[0]["resource_type"] == "orchestrator"
    assert calls[1]["resource_id"] == "orchestrator:orchestrator-supervisor-agent:runtime:runtime-1"
    assert calls[1]["resource_type"] == "agent_runtime"
    assert calls[1]["parent_resource_id"] == "orchestrator-supervisor-agent"
