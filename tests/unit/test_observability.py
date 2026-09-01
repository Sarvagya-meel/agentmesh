import sys
from contextlib import contextmanager
from types import SimpleNamespace

from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.observability import (
    agentmesh_span,
    resolve_trace_author,
    trace_author_metadata,
)


def test_resolve_trace_author_prefers_agent_card_name() -> None:
    card = AgentCard(
        agent_id="agent-1",
        name="Readable Agent",
        owner="platform-team",
        metadata={"runtime_instance_id": "runtime-1"},
    )

    author = resolve_trace_author("agent-1", agent_card=card)

    assert author.author_id == "agent-1"
    assert author.author_name == "Readable Agent"
    assert author.author_type == "agent"
    assert author.author_owner == "platform-team"
    assert author.runtime_instance_id == "runtime-1"


def test_resolve_trace_author_falls_back_to_system_entity_name() -> None:
    author = resolve_trace_author("agentmesh-registry")

    assert author.author_name == "AgentMesh Registry"
    assert author.author_type == "registry"


def test_trace_author_metadata_uses_author_fields_without_secret_leakage() -> None:
    author = resolve_trace_author("agentmesh-control-plane")

    metadata = trace_author_metadata(author)

    assert metadata["author_name"] == "AgentMesh Control Plane"
    assert metadata["author_id"] == "agentmesh-control-plane"
    assert metadata["author_type"] == "control_plane"
    assert metadata["author_resource_id"] == "agentmesh-control-plane"


def test_span_redacts_sensitive_inputs(monkeypatch) -> None:
    captured = {}

    @contextmanager
    def fake_trace(**kwargs):
        captured.update(kwargs)
        yield SimpleNamespace(end=lambda **_kwargs: None)

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setitem(sys.modules, "langsmith.run_helpers", SimpleNamespace(trace=fake_trace))

    with agentmesh_span(
        "test",
        inputs={"prompt": "hidden qa secret", "workflow_id": "workflow"},
    ):
        pass

    assert "prompt" not in captured["inputs"]
    assert captured["inputs"]["prompt_size"] > 0
    assert captured["inputs"]["workflow_id"] == "workflow"
    assert "hidden qa secret" not in str(captured)


def test_langsmith_enter_failure_does_not_change_application(monkeypatch) -> None:
    @contextmanager
    def broken_trace(**_kwargs):
        raise RuntimeError("LangSmith unavailable")
        yield

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setitem(
        sys.modules, "langsmith.run_helpers", SimpleNamespace(trace=broken_trace)
    )

    with agentmesh_span("test") as run:
        assert run is None


def test_langsmith_end_failure_is_swallowed(monkeypatch) -> None:
    class BrokenRun:
        def end(self, **_kwargs) -> None:
            raise RuntimeError("export failed")

    @contextmanager
    def fake_trace(**_kwargs):
        yield BrokenRun()

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setitem(sys.modules, "langsmith.run_helpers", SimpleNamespace(trace=fake_trace))

    with agentmesh_span("test") as run:
        run.end(outputs={"ok": True})
