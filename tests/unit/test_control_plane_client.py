import json
from uuid import uuid4

import httpx
from langchain_core.messages import HumanMessage

from agentmesh.agents.common.control_plane_client import AsyncControlPlaneClient


async def test_async_result_submission_serializes_framework_objects() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "COMPLETED"})

    client = AsyncControlPlaneClient(
        "http://test",
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.submit_result(
            "langgraph-copilot",
            uuid4(),
            worker_id="worker-1",
            claim_token=uuid4(),
            status="COMPLETED",
            result={"messages": [HumanMessage(content="serialized")]},
        )
    finally:
        await client.close()

    result = captured["result"]
    assert isinstance(result, dict)
    messages = result["messages"]
    assert isinstance(messages, list)
    assert messages[0]["content"] == "serialized"
