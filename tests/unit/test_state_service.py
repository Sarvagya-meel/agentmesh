from uuid import uuid4

from agentmesh.core.models import Event
from agentmesh.services.event_service import EventService
from agentmesh.services.state_service import StateService
from agentmesh.storage.repository import InMemoryEventRepository


def test_projection_is_reconstructable_and_deterministic() -> None:
    workflow_id = uuid4()
    event_service = EventService(InMemoryEventRepository())
    event_service.append(
        Event(
            conversation_id="conversation-state",
            workflow_id=workflow_id,
            event_type="WORKFLOW_STARTED",
            source_agent="orchestrator",
            payload={"goal": "Test projection"},
        )
    )
    event_service.append(
        Event(
            conversation_id="conversation-state",
            workflow_id=workflow_id,
            event_type="PLAN_APPROVAL_REQUESTED",
            source_agent="orchestrator",
            payload={"approval": {"prompt": "Approve?"}},
        )
    )
    events = event_service.replay(workflow_id)

    first = StateService.project(events)
    second = StateService.project(events)

    assert first == second
    assert first.status == "AWAITING_PLAN_APPROVAL"
    assert first.last_event_id == events[-1].event_id
