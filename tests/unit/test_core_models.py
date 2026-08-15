from __future__ import annotations

from uuid import uuid4

import pytest

from agentmesh.core.event_types import VALID_EVENT_TYPES
from agentmesh.core.exceptions import CausationLoopError, InvalidEventTypeError, InvalidRoutingError
from agentmesh.core.models import Event, RoutingMode, WorkflowState


def test_valid_event_types_are_registered() -> None:
    assert "WORKFLOW_STARTED" in VALID_EVENT_TYPES
    assert "TASK_ASSIGNED" in VALID_EVENT_TYPES


def test_valid_event_passes_routing_validation() -> None:
    workflow_id = uuid4()
    event = Event(
        conversation_id="conversation-1",
        workflow_id=workflow_id,
        event_type="WORKFLOW_STARTED",
        source_agent="orchestrator",
        routing_mode=RoutingMode.DIRECTED,
        target_agent="job_detector",
        payload={"goal": "Find a role"},
    )

    assert event.workflow_id == workflow_id
    assert event.target_agent == "job_detector"
    assert event.event_type == "WORKFLOW_STARTED"


def test_directed_events_require_target_agent() -> None:
    with pytest.raises(InvalidRoutingError):
        Event(
            conversation_id="conversation-1",
            workflow_id=uuid4(),
            event_type="TASK_ASSIGNED",
            source_agent="orchestrator",
            routing_mode=RoutingMode.DIRECTED,
            payload={"task_type": "JOB_DETECT"},
        )


def test_fanout_events_cannot_set_target_agent() -> None:
    with pytest.raises(InvalidRoutingError):
        Event(
            conversation_id="conversation-1",
            workflow_id=uuid4(),
            event_type="TASK_ASSIGNED",
            source_agent="orchestrator",
            routing_mode=RoutingMode.FANOUT,
            target_agent="job_detector",
            payload={"task_type": "JOB_DETECT"},
        )


def test_invalid_event_type_is_rejected() -> None:
    with pytest.raises(InvalidEventTypeError):
        Event(
            conversation_id="conversation-1",
            workflow_id=uuid4(),
            event_type="NOT_A_REAL_EVENT",
            source_agent="orchestrator",
        )


def test_workflow_state_requires_valid_uuid() -> None:
    state = WorkflowState(
        conversation_id="conversation-1",
        workflow_id=uuid4(),
        status="RUNNING",
        current_step="detect_jobs",
    )

    assert state.status == "RUNNING"


def test_causation_chain_self_reference_is_rejected() -> None:
    event_id = uuid4()
    with pytest.raises(CausationLoopError):
        Event(
            event_id=event_id,
            conversation_id="conversation-1",
            workflow_id=uuid4(),
            event_type="WORKFLOW_STARTED",
            source_agent="orchestrator",
            causation_chain=[event_id],
        )
