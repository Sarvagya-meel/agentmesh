from uuid import UUID, uuid4

from agentmesh.core.models import Event, RoutingMode
from agentmesh.services.service_agentmesh_server.database.repository import (
    InMemoryEventRepository,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.validation import TaskOutputValidator


def test_validation_is_hash_idempotent_and_persisted() -> None:
    event_service = EventService(InMemoryEventRepository())
    task_id = uuid4()
    assignment = event_service.append(
        Event(
            conversation_id="conversation",
            workflow_id=uuid4(),
            event_type="TASK_ASSIGNED",
            source_agent="supervisor",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="worker",
            payload={"task": {"task_id": str(task_id)}},
        )
    )
    validator = TaskOutputValidator(event_service)

    first = validator.validate(
        assignment, task_id=task_id, status="COMPLETED", result={"answer": "done"}
    )
    second = validator.validate(
        assignment, task_id=task_id, status="COMPLETED", result={"answer": "done"}
    )

    assert first == second
    events = event_service.replay(UUID(str(assignment.workflow_id)))
    assert [event.event_type for event in events].count("TASK_VALIDATION_COMPLETED") == 1


def test_validation_rejects_error_output() -> None:
    event_service = EventService(InMemoryEventRepository())
    task_id = uuid4()
    assignment = event_service.append(
        Event(
            conversation_id="conversation",
            workflow_id=uuid4(),
            event_type="TASK_ASSIGNED",
            source_agent="supervisor",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="worker",
            payload={"task": {"task_id": str(task_id)}},
        )
    )

    decision = TaskOutputValidator(event_service).validate(
        assignment, task_id=task_id, status="COMPLETED", result={"error": "bad"}
    )

    assert decision.valid is False
    assert "no_error_marker" in decision.reasons


def test_validation_accepts_durable_agent_approval_output() -> None:
    event_service = EventService(InMemoryEventRepository())
    task_id = uuid4()
    assignment = event_service.append(
        Event(
            conversation_id="conversation",
            workflow_id=uuid4(),
            event_type="TASK_ASSIGNED",
            source_agent="supervisor",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="worker",
            payload={"task": {"task_id": str(task_id)}},
        )
    )

    decision = TaskOutputValidator(event_service).validate(
        assignment,
        task_id=task_id,
        status="AWAITING_APPROVAL",
        result={"thread_id": "durable-thread", "draft_reply": "review me"},
    )

    assert decision.valid is True
