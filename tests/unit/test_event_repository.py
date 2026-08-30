from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from agentmesh.core.database.repository import InMemoryEventRepository
from agentmesh.core.models import Event, RoutingMode
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.services.service_agentmesh_server.events.service import EventService


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


def test_event_service_trace_metadata_resolves_agent_card_names(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    @contextmanager
    def fake_span(name: str, **kwargs: Any) -> Any:
        captured["name"] = name
        captured["metadata"] = kwargs["metadata"]
        yield None

    cards = {
        "source-agent": AgentCard(agent_id="source-agent", name="Source Agent"),
        "target-agent": AgentCard(agent_id="target-agent", name="Target Agent"),
    }
    monkeypatch.setattr(
        "agentmesh.services.service_agentmesh_server.events.service.agentmesh_span",
        fake_span,
    )
    service = EventService(InMemoryEventRepository(), agent_resolver=cards.get)

    service.append(
        Event(
            conversation_id="conversation",
            workflow_id=uuid4(),
            event_type="TASK_ASSIGNED",
            source_agent="source-agent",
            routing_mode=RoutingMode.DIRECTED,
            target_agent="target-agent",
            payload={"task": {"task_id": str(uuid4())}},
        )
    )

    assert "Source Agent" in captured["name"]
    assert captured["metadata"]["source_agent_name"] == "Source Agent"
    assert captured["metadata"]["target_agent_name"] == "Target Agent"
    assert captured["metadata"]["author_name"] == "Source Agent"
