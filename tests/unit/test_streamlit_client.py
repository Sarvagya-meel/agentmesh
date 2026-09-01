from pathlib import Path

import httpx

from agentmesh.services.service_agentmesh_ui.client import ControlPlaneClient


def json_response(url: str, payload: object) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


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


def test_workflow_playground_has_independent_tabs_and_state() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/agentmesh/services/service_agentmesh_ui/app.py").read_text()

    assert '["Orchestration", "Open existing"]' in app_source
    assert '"active_orchestration_workflow_id": None' in app_source
    assert '"opened_workflow_id": None' in app_source
    assert "st.session_state[workflow_state_key]" in app_source
    assert "active_workflow_id" not in app_source
