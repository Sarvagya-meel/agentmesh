from types import SimpleNamespace

import langsmith

from agentmesh.config import Settings
from agentmesh.services.service_agentmesh_server.trace_links import (
    resolve_langsmith_trace_link,
)


def test_trace_link_is_hidden_when_tracing_is_disabled() -> None:
    result = resolve_langsmith_trace_link(Settings(langsmith_tracing=False), "request-1")

    assert result["tracing_enabled"] is False
    assert result["available"] is False
    assert "url" not in result


def test_trace_link_uses_sdk_url_without_exposing_key(monkeypatch) -> None:
    captured = {}
    run = SimpleNamespace(id="run-1")

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def list_runs(self, **kwargs):
            captured.update(kwargs)
            return iter([run])

        def get_run_url(self, **kwargs):
            captured.update(kwargs)
            return "https://smith.langchain.com/trace/run-1"

    monkeypatch.setattr(langsmith, "Client", FakeClient)
    result = resolve_langsmith_trace_link(
        Settings(
            langsmith_tracing=True,
            langsmith_api_key="secret-test-key",
            langsmith_project="agentmesh-test",
        ),
        "request-1",
    )

    assert result["available"] is True
    assert result["url"] == "https://smith.langchain.com/trace/run-1"
    assert "secret-test-key" not in str(result)
    assert "request-1" in str(captured["filter"])


def test_trace_lookup_failure_is_non_authoritative(monkeypatch) -> None:
    class BrokenClient:
        def __init__(self, **_kwargs):
            raise RuntimeError("offline")

    monkeypatch.setattr(langsmith, "Client", BrokenClient)
    result = resolve_langsmith_trace_link(
        Settings(langsmith_tracing=True, langsmith_api_key="secret-test-key"),
        "request-1",
    )

    assert result["tracing_enabled"] is True
    assert result["available"] is False
    assert "secret-test-key" not in str(result)
