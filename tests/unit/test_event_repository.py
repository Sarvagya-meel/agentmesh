from uuid import uuid4

from agentmesh.core.database.repository import InMemoryEventRepository
from agentmesh.core.models import Event, RoutingMode


def test_assignment_with_proposed_output_is_not_relisted_while_waiting_for_approval() -> None:
    repository = InMemoryEventRepository()
    workflow_id = uuid4()
    task_id = uuid4()
    assignment = repository.append(
        Event(
            conversation_id="approval-claim-loop",
            workflow_id=workflow_id,
            event_type="TASK_ASSIGNED",
            source_agent="orchestrator",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="langgraph-copilot",
            payload={"task": {"task_id": str(task_id), "description": "Draft it"}},
        )
    )
    repository.append(
        Event(
            conversation_id="approval-claim-loop",
            workflow_id=workflow_id,
            event_type="AGENT_OUTPUT_PROPOSED",
            source_agent="langgraph-copilot",
            causation_id=assignment.event_id,
            payload={
                "task_id": str(task_id),
                "assignment_event_id": str(assignment.event_id),
                "result": {"thread_id": "approval-claim-loop"},
            },
        )
    )

    assert repository.list_pending_assignments("langgraph-copilot") == []


def test_completed_assignment_is_not_pending_even_without_output_approval() -> None:
    repository = InMemoryEventRepository()
    workflow_id = uuid4()
    task_id = uuid4()
    repository.append(
        Event(
            conversation_id="completed-assignment",
            workflow_id=workflow_id,
            event_type="TASK_ASSIGNED",
            source_agent="orchestrator",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="googleADK-Chatagent",
            payload={"task": {"task_id": str(task_id), "description": "Answer it"}},
        )
    )
    repository.append(
        Event(
            conversation_id="completed-assignment",
            workflow_id=workflow_id,
            event_type="TASK_COMPLETED",
            source_agent="googleADK-Chatagent",
            payload={"task_id": str(task_id), "result": {"answer": "done"}},
        )
    )

    assert repository.list_pending_assignments("googleADK-Chatagent") == []
