from typing import Any

from httpx import ASGITransport, AsyncClient

from agentmesh.agents.agent_langgraph_copilot.agent import ConversationAgent
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.runtime import create_agent_runtime_app
from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ModelProviderError


def conversation_factory(
    settings: Settings,
) -> tuple[ConversationAgent, Any]:
    del settings
    return ConversationAgent(auto_register=False), lambda: None


class ProviderFailureAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("provider-failure", auto_register=False)

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        del task_payload
        raise ModelProviderError("Model provider is unavailable.")


def provider_failure_factory(settings: Settings) -> tuple[BaseAgent, Any]:
    del settings
    return ProviderFailureAgent(), lambda: None


async def test_agent_runtime_exposes_health_card_and_invoke() -> None:
    app = create_agent_runtime_app(
        kind="langgraph",
        factory=conversation_factory,
        worker_enabled=False,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            card = await client.get("/agent-card")
            invoked = await client.post("/invoke", json={"message": "Plan Dubai"})

    assert health.json() == {
        "status": "ok",
        "agent_id": "langgraph-copilot",
        "runtime_role": "api",
    }
    assert card.json()["agent_id"] == "langgraph-copilot"
    assert invoked.json()["status"] == "COMPLETED"
    assert "Plan Dubai" in invoked.json()["final_reply"]


async def test_langgraph_runtime_resumes_approval_conversation() -> None:
    app = create_agent_runtime_app(
        kind="langgraph",
        factory=conversation_factory,
        worker_enabled=False,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            invoked = await client.post(
                "/invoke",
                json={"message": "Plan Dubai", "approval_required": True},
            )
            thread_id = invoked.json()["thread_id"]
            resumed = await client.post(
                f"/conversations/{thread_id}/resume",
                json={"decision": "approve"},
            )

    assert invoked.json()["status"] == "AWAITING_APPROVAL"
    assert resumed.json()["status"] == "COMPLETED"
    assert resumed.json()["final_reply"] == invoked.json()["draft_reply"]


async def test_agent_runtime_reports_ready_when_worker_mode_is_disabled() -> None:
    app = create_agent_runtime_app(
        kind="langgraph",
        factory=conversation_factory,
        worker_enabled=False,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "runtime_role": "api",
        "presence_enabled": False,
    }


async def test_runtime_factory_is_called_once_and_worker_has_no_invoke_route() -> None:
    calls = 0

    def counted_factory(settings: Settings) -> tuple[ConversationAgent, Any]:
        nonlocal calls
        calls += 1
        return conversation_factory(settings)

    app = create_agent_runtime_app(
        kind="langgraph",
        factory=counted_factory,
        runtime_role="worker",
        worker_enabled=False,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            invoked = await client.post("/invoke", json={"message": "not allowed"})
            card = await client.get("/agent-card")

    assert calls == 1
    assert health.json()["runtime_role"] == "worker"
    assert invoked.status_code == 404
    assert card.status_code == 404


async def test_api_role_keeps_direct_invoke_route() -> None:
    app = create_agent_runtime_app(
        kind="langgraph",
        factory=conversation_factory,
        runtime_role="api",
        worker_enabled=False,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            invoked = await client.post("/invoke", json={"message": "hello"})

    assert invoked.status_code == 200


async def test_direct_invoke_maps_model_provider_failure_to_503() -> None:
    app = create_agent_runtime_app(
        kind="provider-failure",
        factory=provider_failure_factory,
        worker_enabled=False,
    )

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            invoked = await client.post("/invoke", json={"message": "hello"})

    assert invoked.status_code == 503
    assert invoked.json() == {"detail": "Model provider is unavailable."}
