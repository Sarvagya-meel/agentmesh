from pathlib import Path

import httpx

from agentmesh.services.service_agentmesh_ui.client import ControlPlaneClient
from agentmesh.services.service_agentmesh_ui.view_models import (
    activity_hash,
    event_label,
    event_route,
    newest_events,
    normalize_registry_url,
)


def json_response(url: str, payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


def post_response(url: str, payload: object) -> httpx.Response:
    return httpx.Response(202, json=payload, request=httpx.Request("POST", url))


def test_ui_client_reads_registry_and_cursor_activity(monkeypatch) -> None:
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        payload = {"workflow": {}, "events": [], "next_sequence": 4}
        if url.endswith("/registry/resources"):
            payload = []
        return json_response(url, payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    client = ControlPlaneClient("http://control-plane:8000")

    assert client.list_resources() == []
    activity = client.workflow_activity("workflow-1", after_sequence=3)

    assert activity["next_sequence"] == 4
    assert calls[1][1] == {"after_sequence": 3, "limit": 100}


def test_ui_client_checks_registry_health(monkeypatch) -> None:
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        return json_response(url, {"status": "ok", "service": "control-plane"})

    monkeypatch.setattr(httpx, "get", fake_get)
    client = ControlPlaneClient("http://control-plane:8000/")

    assert client.health()["status"] == "ok"
    assert calls == [("http://control-plane:8000/health", 30.0)]


def test_local_ui_rewrites_docker_agent_endpoints_for_direct_requests(
    monkeypatch,
) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        return json_response(url, {"status": "COMPLETED"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = ControlPlaneClient("http://127.0.0.1:8000")
    card = {
        "agent_id": "langgraph-copilot",
        "endpoint": "http://agent-langgraph-copilot:8101",
        "metadata": {
            "direct_endpoint": "http://agent-langgraph-copilot:8101",
        },
    }

    client.invoke_agent(card, "Draft a reply", approval_required=False)
    client.resume_agent(card, "thread-1", "revise", feedback="Add evidence")

    assert calls == [
        (
            "http://127.0.0.1:8101/invoke",
            {"message": "Draft a reply", "approval_required": False},
        ),
        (
            "http://127.0.0.1:8101/conversations/thread-1/resume",
            {"decision": "revise", "feedback": "Add evidence"},
        ),
    ]


def test_docker_ui_keeps_docker_agent_endpoint(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return json_response(url, {"status": "success"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = ControlPlaneClient("http://control-plane:8000")
    card = {
        "agent_id": "googleADK-Chatagent",
        "endpoint": "http://agent-googleadk-chatagent:8102",
    }

    client.invoke_agent(card, "Hello")

    assert calls == ["http://agent-googleadk-chatagent:8102/invoke"]


def test_streamlit_runtime_has_no_database_access() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/agentmesh/services/service_agentmesh_ui/app.py").read_text()
    client_source = (
        root / "src/agentmesh/services/service_agentmesh_ui/client.py"
    ).read_text()
    compose = (root / "deployment/docker/compose.yml").read_text()
    streamlit_section = compose.split("  streamlit:", maxsplit=1)[1].split(
        "\nvolumes:", maxsplit=1
    )[0]

    assert "psycopg" not in app_source + client_source
    assert "DATABASE_URL" not in app_source + client_source
    assert "DATABASE_URL" not in streamlit_section


def test_supervisor_runtime_uses_postgres_registry_resources() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "deployment/docker/compose.yml").read_text()
    supervisor_section = compose.split("  supervisor:", maxsplit=1)[1].split(
        "\n  agent-langgraph-copilot:", maxsplit=1
    )[0]

    assert "REGISTRY_BACKEND: postgres" in supervisor_section
    assert "DATABASE_URL: postgresql://agentmesh:agentmesh@postgres:5432/agentmesh" in (
        supervisor_section
    )


def test_agent_playground_scopes_messages_by_agent_and_execution_mode() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/agentmesh/services/service_agentmesh_ui/app.py").read_text()

    assert '"agent_messages_by_scope": {}' in app_source
    assert '"pending_direct_input_by_scope": {}' in app_source
    assert '"active_queue_id_by_scope": {}' in app_source
    assert "agent_playground_scope(agent_id, mode)" in app_source
    assert "agent_messages\": []" not in app_source
    assert "active_queue_id\": None" not in app_source


def test_workflow_playground_has_independent_tabs_and_state() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/agentmesh/services/service_agentmesh_ui/app.py").read_text()

    assert '["Orchestration", "Open existing"]' in app_source
    assert '"active_orchestration_workflow_id": None' in app_source
    assert '"opened_workflow_id": None' in app_source
    assert "st.session_state[workflow_state_key]" in app_source
    assert "active_workflow_id" not in app_source


def test_workflow_start_button_is_not_disabled_by_stale_form_state() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/agentmesh/services/service_agentmesh_ui/app.py").read_text()
    submit_line = 'st.form_submit_button("Start workflow", type="primary")'

    assert submit_line in app_source
    assert '"Enter a workflow goal before starting."' in app_source
    assert '"Start workflow", type="primary", disabled=not goal.strip()' not in app_source


def test_workflow_activity_uses_three_columns_and_top_page_navigation() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/agentmesh/services/service_agentmesh_ui/app.py").read_text()

    assert "recovery_column, workspace_column, event_column = st.columns(" in app_source
    assert '[1, 1, 1], gap="medium"' in app_source
    assert 'key="main-page-navigation"' in app_source
    assert "st.sidebar.radio" not in app_source
    assert 'st.subheader("Live event trail")' in app_source
    assert '"View",' in app_source
    assert 'help="View the complete raw event record"' in app_source
    assert "json.dumps(event_object, indent=2, default=str)" in app_source
    assert 'f"**{sequence_number}. {event_label(event_object)}**"' in app_source
    assert 'st.form("registry-connection")' in app_source
    assert 'value=requested_default' in app_source
    assert '"Connect",' in app_source
    assert '"Disconnect",' in app_source
    assert '"registry_url": None' in app_source
    assert 'st.info("Registry is not connected.")' in app_source
    assert 'st.warning("Connect to a registry from the Registry page first.")' in app_source
    assert 'key=f"direct-interrupt-{scope}-{option[\'value\']}"' in app_source
    assert 'draft_reply = pending.get("draft_reply")' in app_source
    assert '"Require human approval"' in app_source
    assert 'key="workflow-approval-required"' in app_source
    assert 'key=f"agent-approval-required-{scope}"' in app_source
    assert 'key=f"plan-step-{step_key}"' in app_source
    assert 'f"**{step_number}.) {step_name}**"' in app_source
    assert '"View input"' in app_source
    assert '"View output"' in app_source
    assert 'event.get("event_type") != "TASK_ASSIGNED"' in app_source
    assert '"dispatched_task": dispatched_task' in app_source
    assert '"**Resolved dependency context**"' in app_source
    assert 'st.json(resolved_inputs, expanded=True)' in app_source
    assert 'f"**GOAL:** {main_goal}"' in app_source
    assert 'f"**Agent Name:** {agent_name}"' in app_source
    assert 'f"**Agent Capability:** {capability}"' in app_source
    assert 'f"**Agent Goal:** {agent_goal}"' in app_source
    assert 'f"**Agent Goal Description:** {goal_description}"' in app_source
    assert 'f"**Agent Goal Expected:** {expected_goal}"' in app_source
    assert 'f"**Agent Dependency:** {dependency_text}"' in app_source
    assert '"Investigate checkpoint"' in app_source
    assert '"Parent workflow ID:' in app_source
    assert "Performs read-only replay" in app_source
    assert "Continues a non-terminal checkpoint" in app_source
    assert "@st.fragment(run_every=2.0, parallel=True)" in app_source
    assert "def monitor_activity(workflow_id: str)" in app_source
    assert 'state.get("rendered_hash") != digest' in app_source
    assert "@st.fragment(run_every=1.5)\ndef render_live_activity(" not in app_source


def test_streamlit_client_sends_request_scoped_approval_policy(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        return post_response(url, {"workflow_id": "workflow-1"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = ControlPlaneClient("http://control-plane:8000")

    client.start_workflow(
        "Review a proposal",
        ["review-agent"],
        "conversation-1",
        approval_required=False,
    )
    client.submit_assignment(
        "langgraph-copilot",
        "Draft a reply",
        "conversation-2",
        approval_required=False,
    )

    assert calls == [
        (
            "http://control-plane:8000/workflows/start",
            {
                "conversation_id": "conversation-1",
                "goal": "Review a proposal",
                "preferred_agent_ids": ["review-agent"],
                "approval_required": False,
            },
        ),
        (
            "http://control-plane:8000/workers/langgraph-copilot/assignments",
            {
                "message": "Draft a reply",
                "conversation_id": "conversation-2",
                "approval_required": False,
            },
        ),
    ]


def test_event_trail_view_model_orders_and_labels_routes() -> None:
    events = [
        {
            "sequence_number": 4,
            "event_type": "TASK_ASSIGNED",
            "source_agent": "control-plane",
            "target_agent": "worker",
        },
        {
            "sequence_number": 9,
            "event_type": "TASK_COMPLETED",
            "source_agent": "worker",
            "target_agent": "control-plane",
        },
    ]

    ordered = newest_events(events)

    assert [event["sequence_number"] for event in ordered] == [9, 4]
    assert event_route(ordered[0]) == "worker -> control-plane"
    assert event_label(ordered[0]) == "Task Completed"


def test_activity_hash_only_changes_when_activity_data_changes() -> None:
    activity = {"workflow": {"status": "RUNNING"}, "events": []}

    first = activity_hash(activity)
    same_data = activity_hash({"events": [], "workflow": {"status": "RUNNING"}})
    changed = activity_hash({"workflow": {"status": "COMPLETED"}, "events": []})

    assert first == same_data
    assert changed != first


def test_registry_url_normalization() -> None:
    assert normalize_registry_url(" http://localhost:8000/ ") == "http://localhost:8000"
    assert normalize_registry_url("https://registry.example/api/") == (
        "https://registry.example/api"
    )

    for invalid in ["localhost:8000", "ftp://localhost:8000", "http://localhost?a=1"]:
        try:
            normalize_registry_url(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected {invalid!r} to be rejected")


def test_streamlit_client_routes_checkpoint_replay_recover_and_reruns(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        return post_response(
            url,
            {"workflow_id": "new-workflow", "recovery_workflow_id": "recovery"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = ControlPlaneClient("http://control-plane:8000")

    replay = client.replay_checkpoint("workflow-1", "checkpoint-1")
    assert replay["workflow_id"] == "new-workflow"
    recovered = client.recover_checkpoint("workflow-1", "checkpoint-1")
    assert recovered["recovery_workflow_id"] == "recovery"
    assert client.rerun_workflow("workflow-1")["workflow_id"] == "new-workflow"
    assert client.rerun_task("workflow-1", "task-1")["workflow_id"] == "new-workflow"

    assert calls == [
        (
            "http://control-plane:8000/workflows/workflow-1/replay",
            {"checkpoint_id": "checkpoint-1"},
        ),
        (
            "http://control-plane:8000/workflows/workflow-1/recover",
            {"checkpoint_id": "checkpoint-1", "new_workflow_id": None},
        ),
        ("http://control-plane:8000/workflows/workflow-1/rerun", {}),
        ("http://control-plane:8000/workflows/workflow-1/tasks/task-1/rerun", {}),
    ]
