from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from agentmesh.agents.common.worker import AssignmentWorker
from agentmesh.services.service_agentmesh_server.app import app


@pytest.mark.parametrize(
    ("agent_id", "capabilities"),
    [
        ("langgraph-copilot", ["CHAT", "REVIEW"]),
        ("googleADK-Chatagent", ["CHAT", "REVIEW", "ADK"]),
    ],
)
async def test_claimed_worker_completes_orchestrated_task(
    agent_id: str,
    capabilities: list[str],
) -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            registration = await client.post(
                "/registry/agents",
                json={
                    "agent_id": agent_id,
                    "name": agent_id,
                    "capabilities": capabilities,
                    "status": "online",
                },
            )
            assert registration.status_code == 201

            started = await client.post(
                "/workflows/start",
                json={
                    "conversation_id": f"conversation-{agent_id}",
                    "goal": "Explain why event sourcing is useful.",
                    "preferred_agent_ids": [agent_id],
                },
            )
            workflow_id = started.json()["workflow_id"]
            assignment_state = await client.post(
                f"/workflows/{workflow_id}/approvals",
                json={"decision": "APPROVE"},
            )
            assert assignment_state.json()["status"] == "WAITING_FOR_AGENT"

            pending = await client.get(f"/workers/{agent_id}/assignments")
            assert pending.status_code == 200
            assignment = pending.json()[0]
            worker_id = str(uuid4())
            claim = await client.post(
                f"/workers/{agent_id}/assignments/{assignment['event_id']}/claim",
                json={"worker_id": worker_id},
            )
            assert claim.status_code == 200
            duplicate_claim = await client.post(
                f"/workers/{agent_id}/assignments/{assignment['event_id']}/claim",
                json={"worker_id": worker_id},
            )
            assert duplicate_claim.status_code == 409

            result = await client.post(
                f"/workers/{agent_id}/assignments/{assignment['event_id']}/result",
                json={
                    "worker_id": worker_id,
                    "claim_token": claim.json()["claim_token"],
                    "status": "COMPLETED",
                    "result": {"answer": f"completed by {agent_id}"},
                },
            )
            assert result.status_code == 200
            assert result.json()["status"] == "COMPLETED"

            events = await client.get("/events", params={"workflow_id": workflow_id})
            completed = [
                event for event in events.json() if event["event_type"] == "TASK_COMPLETED"
            ]
            assert completed[0]["causation_id"] == assignment["event_id"]


async def test_no_registered_agent_fails_planning_and_records_failure() -> None:
    workflow_id = str(uuid4())
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post(
                "/workflows/start",
                json={
                    "conversation_id": "conversation-no-agent",
                    "workflow_id": workflow_id,
                    "goal": "Handle this without registered agents.",
                },
            )
            assert started.status_code == 422

            state = await client.get(f"/state/{workflow_id}")
            assert state.status_code == 200
            assert state.json()["status"] == "FAILED"


async def test_all_selected_agents_are_included_in_the_plan() -> None:
    agent_ids = ["langgraph-copilot", "googleADK-Chatagent"]
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for agent_id in agent_ids:
                response = await client.post(
                    "/registry/agents",
                    json={
                        "agent_id": agent_id,
                        "name": agent_id,
                        "capabilities": ["CHAT", "REVIEW"],
                        "status": "online",
                    },
                )
                assert response.status_code == 201

            started = await client.post(
                "/workflows/start",
                json={
                    "conversation_id": "conversation-all-agents",
                    "goal": "Draft and review an explanation of event sourcing.",
                    "preferred_agent_ids": agent_ids,
                },
            )
            assert started.status_code == 201
            planned_agents = {task["agent_id"] for task in started.json()["plan"]["tasks"]}
            assert planned_agents == set(agent_ids)


async def test_directed_playground_assignment_uses_claim_and_event_contract() -> None:
    agent_id = "queued-agent"
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/registry/agents",
                json={
                    "agent_id": agent_id,
                    "name": agent_id,
                    "capabilities": ["CHAT"],
                    "status": "online",
                },
            )
            queued = await client.post(
                f"/workers/{agent_id}/assignments",
                json={"message": "Make Dubai travel plans"},
            )
            assert queued.status_code == 202
            workflow_id = queued.json()["workflow_id"]

            pending = await client.get(f"/workers/{agent_id}/assignments")
            assignment = pending.json()[0]
            assert assignment["payload"]["standalone"] is True
            assert assignment["payload"]["task"]["messages"] == ["Make Dubai travel plans"]

            worker_id = str(uuid4())
            claim = await client.post(
                f"/workers/{agent_id}/assignments/{assignment['event_id']}/claim",
                json={"worker_id": worker_id},
            )
            completed = await client.post(
                f"/workers/{agent_id}/assignments/{assignment['event_id']}/result",
                json={
                    "worker_id": worker_id,
                    "claim_token": claim.json()["claim_token"],
                    "status": "COMPLETED",
                    "result": {"answer": "Dubai itinerary"},
                },
            )
            events = await client.get("/events", params={"workflow_id": workflow_id})

    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert [event["event_type"] for event in events.json()] == [
        "TASK_ASSIGNED",
        "TASK_COMPLETED",
    ]


def test_provider_rate_limit_is_retryable_and_honors_retry_hint() -> None:
    class RateLimitError(Exception):
        status_code = 429

    error = RateLimitError("Rate limit reached. Please try again in 11.355s.")

    assert AssignmentWorker._is_retryable_failure(error) is True
    assert AssignmentWorker._retry_after_seconds(error) == 11.355


def test_validation_failure_is_not_retryable() -> None:
    error = ValueError("Invalid task payload")

    assert AssignmentWorker._is_retryable_failure(error) is False
    assert AssignmentWorker._retry_after_seconds(error) is None
