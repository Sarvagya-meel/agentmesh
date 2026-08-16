from uuid import uuid4

from agentmesh.services.orchestrator_service import AgentStep, OrchestratorService


def test_orchestrator_starts_a_three_step_workflow() -> None:
    service = OrchestratorService(
        [
            AgentStep("detect_jobs", "JOB_DETECT", "job_detector", "Find matching roles"),
            AgentStep("find_email", "EMAIL_FIND", "email_finder", "Find the contact email"),
            AgentStep("apply", "APPLY", "applicator", "Submit the application"),
        ]
    )

    workflow_id = uuid4()
    state, events = service.start_workflow(
        "conversation-1",
        "Find and apply to a suitable software role",
        workflow_id=workflow_id,
    )

    assert state.workflow_id == workflow_id
    assert state.status == "RUNNING"
    assert [event.event_type for event in events] == [
        "WORKFLOW_STARTED",
        "TASK_ASSIGNED",
        "TASK_ASSIGNED",
        "TASK_ASSIGNED",
    ]
    assert [event.target_agent for event in events if event.event_type == "TASK_ASSIGNED"] == [
        "job_detector",
        "email_finder",
        "applicator",
    ]


def test_orchestrator_routes_to_runtime_selected_agents() -> None:
    service = OrchestratorService(
        [
            AgentStep("step_1", "CHAT", "custom-chat-agent", "Route chat request"),
            AgentStep("step_2", "CHAT", "review-helper", "Route chat request"),
        ]
    )

    state, events = service.start_workflow(
        "conversation-ui",
        "Help with this request",
        workflow_id=uuid4(),
    )

    assert state.assigned_agents == ["custom-chat-agent", "review-helper"]
    assert [event.target_agent for event in events if event.event_type == "TASK_ASSIGNED"] == [
        "custom-chat-agent",
        "review-helper",
    ]


def test_orchestrator_advances_to_the_next_task() -> None:
    service = OrchestratorService(
        [
            AgentStep("detect_jobs", "JOB_DETECT", "job_detector", "Find matching roles"),
            AgentStep("find_email", "EMAIL_FIND", "email_finder", "Find the contact email"),
        ]
    )

    workflow_id = uuid4()
    completed_event, follow_up_events = service.advance_workflow(
        "conversation-1",
        workflow_id,
        completed_task_type="JOB_DETECT",
        completed_agent="job_detector",
        result={"jobs_found": 3},
    )

    assert completed_event.event_type == "TASK_COMPLETED"
    assert follow_up_events[0].event_type == "TASK_ASSIGNED"
    assert follow_up_events[0].target_agent == "email_finder"
