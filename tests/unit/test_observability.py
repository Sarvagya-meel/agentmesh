from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.observability import resolve_trace_author, trace_author_metadata


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
