"""Opt-in acceptance tests against the running combined Docker stack.

Run with AGENTMESH_LIVE_UAT=1. These tests create workflows and may call the
configured model provider; ordinary pytest runs never contact live services.
"""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from agentmesh.services.service_agentmesh_ui.client import ControlPlaneClient

pytestmark = pytest.mark.skipif(
    os.getenv("AGENTMESH_LIVE_UAT") != "1", reason="Requires running Docker stack"
)
APP = Path(__file__).resolve().parents[2] / "src/agentmesh/services/service_agentmesh_ui/app.py"
BASE_URL = os.getenv("AGENTMESH_UAT_URL", "http://127.0.0.1:8000")


@pytest.fixture
def api():
    return ControlPlaneClient(BASE_URL, timeout_seconds=120)


def wait_for(api, workflow_id, statuses, *, approve=False):
    deadline = time.monotonic() + 240
    activity = {}
    while time.monotonic() < deadline:
        activity = api.workflow_activity(workflow_id)
        status = activity["workflow"]["status"]
        if status in statuses:
            return activity
        assert status not in {"FAILED", "CANCELLED"}, json.dumps(activity, default=str)
        if approve and status in {"AWAITING_PLAN_APPROVAL", "AWAITING_AGENT_APPROVAL"}:
            api.submit_approval(workflow_id, "APPROVE")
        time.sleep(2)
    pytest.fail(f"Workflow timed out: {json.dumps(activity, default=str)}")


def assert_ui_ok(app):
    assert not app.exception, [item.message for item in app.exception]
    assert not app.error, [item.value for item in app.error]


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert_ui_ok(app)


def connected_app():
    app = AppTest.from_file(str(APP), default_timeout=180).run()
    assert_ui_ok(app)
    assert app.session_state.registry_url is None
    app.text_input[0].set_value(BASE_URL)
    click(app, "Connect")
    assert app.session_state.registry_url == BASE_URL
    return app


def test_streamlit_registry_navigation_disconnect(api):
    app = connected_app()
    assert len(app.dataframe) == 2
    assert any(card["agent_id"] == "orchestrator-supervisor-agent" for card in api.list_agents())
    for page in ["Agent Playground", "Workflow Playground", "Registry"]:
        app.session_state["main-page-navigation"] = page
        app.run()
        assert_ui_ok(app)
        assert app.session_state.registry_url == BASE_URL
    click(app, "Disconnect")
    assert app.session_state.registry_url is None
    assert not app.session_state.agent_messages_by_scope


@pytest.mark.parametrize("decision", ["approve", "reject", "revise"])
def test_streamlit_direct_human_decisions(decision):
    app = connected_app()
    app.session_state["main-page-navigation"] = "Agent Playground"
    app.run()
    app.selectbox[0].select("langgraph-copilot").run()
    assert app.toggle[0].value is True
    app.chat_input[0].set_value("Write one sentence confirming a release check.").run()
    assert_ui_ok(app)
    assert app.session_state.pending_direct_input_by_scope
    if decision == "revise":
        app.text_area[0].set_value("Include the literal word revisedcheck in the answer.")
        click(app, "Revise")
        assert app.session_state.pending_direct_input_by_scope
        pending = next(iter(app.session_state.pending_direct_input_by_scope.values()))
        assert "revisedcheck" in pending["draft_reply"].lower()
        click(app, "Approve")
    else:
        click(app, decision.title())
    assert not app.session_state.pending_direct_input_by_scope
    assert app.chat_input[0].disabled is False
    saved = dict(app.session_state.agent_messages_by_scope)
    app.session_state["main-page-navigation"] = "Registry"
    app.run()
    app.session_state["main-page-navigation"] = "Agent Playground"
    app.run()
    assert_ui_ok(app)
    assert app.session_state.agent_messages_by_scope == saved


@pytest.mark.parametrize("decision", ["APPROVE", "REJECT", "REVISE"])
def test_queued_human_decisions(api, decision):
    queued = api.submit_assignment(
        "langgraph-copilot", "Write one sentence about release readiness.", str(uuid4())
    )
    workflow_id = queued["workflow_id"]
    wait_for(api, workflow_id, {"AWAITING_AGENT_APPROVAL"})
    api.submit_approval(
        workflow_id, decision, feedback="Include the literal word revisedcheck in your answer."
    )
    if decision == "REVISE":
        revised = wait_for(api, workflow_id, {"AWAITING_AGENT_APPROVAL"})
        assert "revisedcheck" in revised["pending_interrupt"]["draft_reply"].lower()
        api.submit_approval(workflow_id, "APPROVE")
    terminal = wait_for(api, workflow_id, {"FAILED" if decision == "REJECT" else "COMPLETED"})
    assert terminal["terminal"] is True
    if decision == "REJECT":
        assert any(event["event_type"] == "AGENT_OUTPUT_REJECTED" for event in terminal["events"])


def test_workflow_approvals_replay_recovery_and_reruns(api):
    started = api.start_workflow(
        "Write a short release checklist, then review that checklist. Use two dependent steps.",
        ["langgraph-copilot"],
        str(uuid4()),
    )
    workflow_id = started["workflow_id"]
    planned = wait_for(api, workflow_id, {"AWAITING_PLAN_APPROVAL"})
    assert planned["pending_interrupt"]["type"] == "human_approval"
    completed = wait_for(api, workflow_id, {"COMPLETED"}, approve=True)
    events = completed["events"]
    assert events[0]["event_type"] == "WORKFLOW_STARTED"
    assert (
        next(
            i
            for i, event in enumerate(events)
            if event["event_type"] == "SUPERVISOR_ACTION_REQUESTED"
        )
        > 0
    )
    checkpoints = api.checkpoints(workflow_id)
    assert checkpoints
    replay = api.replay_checkpoint(workflow_id, checkpoints[0]["checkpoint_id"])
    assert replay["mode"] == "read_only_replay"
    after = api.workflow_activity(workflow_id)
    assert after["workflow"]["status"] == "COMPLETED"
    assert [e["event_id"] for e in after["events"]] == [e["event_id"] for e in events]
    terminal_checkpoint = next(item for item in checkpoints if not item["next"])
    with pytest.raises(httpx.HTTPStatusError) as invalid_recovery:
        api.recover_checkpoint(workflow_id, terminal_checkpoint["checkpoint_id"])
    assert invalid_recovery.value.response.status_code == 422
    resumable = next(item for item in checkpoints if item["next"])
    recovered = api.recover_checkpoint(workflow_id, resumable["checkpoint_id"])
    child_id = recovered["recovery_workflow_id"]
    assert child_id != workflow_id
    wait_for(api, child_id, {"COMPLETED"}, approve=True)
    task_id = completed["workflow"]["plan"]["tasks"][0]["task_id"]
    for invoke in [
        lambda: api.rerun_workflow(workflow_id),
        lambda: api.rerun_task(workflow_id, task_id),
    ]:
        result = invoke()
        assert result["workflow_id"] != workflow_id
        assert result["rerun_of_workflow_id"] == workflow_id
        wait_for(api, result["workflow_id"], {"COMPLETED"}, approve=True)


def test_live_invalid_request_is_rejected():
    response = httpx.post(f"{BASE_URL}/workflows/start", json={"goal": ""}, timeout=30)
    assert response.status_code == 422


@pytest.mark.parametrize("agent_id", ["langgraph-copilot", "googleADK-Chatagent"])
def test_direct_and_queued_without_approval(api, agent_id):
    card = next(card for card in api.list_agents() if card["agent_id"] == agent_id)
    result = api.invoke_agent(card, "Say ready in one sentence.", approval_required=False)
    assert result["status"] in {"COMPLETED", "success"}
    queued = api.submit_assignment(
        agent_id, "Say ready in one sentence.", str(uuid4()), approval_required=False
    )
    wait_for(api, queued["workflow_id"], {"COMPLETED"})
