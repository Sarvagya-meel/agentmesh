from uuid import uuid4

from agentmesh.core.models import Event, RoutingMode
from agentmesh.services.service_agentmesh_server.activity import (
    normalize_pending_interrupt,
    paginate_events,
    project_standalone_request,
    project_step_views,
)


def make_event(sequence: int, event_type: str, task_id: str) -> Event:
    return Event(
        conversation_id="activity-test",
        workflow_id=uuid4(),
        event_type=event_type,
        source_agent="control-plane",
        payload={"task_id": task_id},
        sequence_number=sequence,
    )


def test_activity_cursor_does_not_skip_or_duplicate_events() -> None:
    task_id = str(uuid4())
    events = [make_event(index, "TASK_COMPLETED", task_id) for index in range(1, 6)]

    first, cursor, has_more = paginate_events(events, after_sequence=0, limit=2)
    second, cursor, has_more_after = paginate_events(
        events, after_sequence=cursor, limit=10
    )

    assert [event.sequence_number for event in first] == [1, 2]
    assert [event.sequence_number for event in second] == [3, 4, 5]
    assert cursor == 5
    assert has_more is True
    assert has_more_after is False


def test_step_projection_tracks_validation_and_completion() -> None:
    task_id = str(uuid4())
    workflow = {
        "plan": {
            "tasks": [
                {
                    "task_id": task_id,
                    "position": 0,
                    "name": "Build",
                    "agent_id": "worker",
                    "required_capability": "CHAT",
                    "dependencies": [],
                    "status": "PROPOSED",
                }
            ]
        }
    }
    validating = project_step_views(
        workflow, [make_event(1, "TASK_VALIDATION_REQUESTED", task_id)]
    )
    completed = project_step_views(
        workflow,
        [
            make_event(1, "TASK_VALIDATION_REQUESTED", task_id),
            make_event(2, "TASK_COMPLETED", task_id),
        ],
    )

    assert validating[0]["status"] == "VALIDATING"
    assert completed[0]["status"] == "COMPLETED"


def test_pending_approval_is_normalized_for_the_ui() -> None:
    pending = normalize_pending_interrupt(
        {
            "approval_id": "approval-1",
            "approval_type": "AGENT_OUTPUT",
            "prompt": "Review the draft.",
            "options": ["approve", "revise", "reject"],
            "context": {"draft_reply": "Draft response"},
        }
    )

    assert pending is not None
    assert pending["type"] == "human_approval"
    assert pending["draft_reply"] == "Draft response"
    assert pending["approval"]["approval_id"] == "approval-1"
    assert pending["options"][0] == {"label": "Approve", "value": "APPROVE"}


def test_standalone_request_projects_one_control_plane_dispatch() -> None:
    workflow_id = uuid4()
    task_id = str(uuid4())
    assignment = Event(
        conversation_id="queued-direct",
        workflow_id=workflow_id,
        event_type="TASK_ASSIGNED",
        source_agent="agentmesh-control-plane",
        routing_mode=RoutingMode.DIRECTED,
        target_agent="worker",
        payload={
            "standalone": True,
            "task": {"task_id": task_id, "description": "Answer directly"},
        },
        sequence_number=1,
    )
    completed = Event(
        conversation_id="queued-direct",
        workflow_id=workflow_id,
        event_type="TASK_COMPLETED",
        source_agent="worker",
        payload={"task_id": task_id, "result": {"answer": "Done"}},
        sequence_number=2,
    )

    projected = project_standalone_request(
        {"workflow_id": str(workflow_id), "status": "RUNNING"},
        [assignment, completed],
    )
    steps = project_step_views(projected, [assignment, completed])

    assert projected["status"] == "COMPLETED"
    assert projected["plan"]["planner_provider"] == "control-plane"
    assert projected["task_results"][0]["result"]["answer"] == "Done"
    assert steps == [
        {
            "task_id": task_id,
            "position": 0,
            "name": "Direct agent request",
            "agent_id": "worker",
            "required_capability": "DIRECT",
            "dependencies": [],
            "status": "COMPLETED",
        }
    ]
