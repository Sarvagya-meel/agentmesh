from typing import Any

from httpx import ASGITransport, AsyncClient

from agentmesh.agents.agent_langgraph_copilot.agent import ConversationAgent
from agentmesh.agents.common.runtime import create_agent_runtime_app
from agentmesh.config import Settings


def conversation_factory(
    settings: Settings,
) -> tuple[ConversationAgent, Any]:
    del settings
    return ConversationAgent(auto_register=False), lambda: None


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

    assert health.json() == {"status": "ok", "agent_id": "langgraph-copilot"}
    assert card.json()["agent_id"] == "langgraph-copilot"
    assert invoked.json()["status"] == "completed"
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

    assert invoked.json()["status"] == "awaiting_human"
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["final_reply"] == invoked.json()["draft_reply"]
