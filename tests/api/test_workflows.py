from httpx import ASGITransport, AsyncClient

from agentmesh.services.service_agentmesh_server.app import app


async def test_workflow_api_runs_both_approval_gates_and_completes() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            registration = await client.post(
                "/registry/agents",
                json={
                    "agent_id": "api-worker",
                    "name": "api-worker",
                    "capabilities": ["CHAT"],
                    "status": "online",
                },
            )
            assert registration.status_code == 201

            started = await client.post(
                "/workflows/start",
                json={
                    "conversation_id": "api-conversation",
                    "goal": "Handle this request",
                    "preferred_agent_ids": ["api-worker"],
                },
            )
            assert started.status_code == 201
            body = started.json()
            workflow_id = body["workflow_id"]
            assert body["status"] == "AWAITING_PLAN_APPROVAL"

            plan_approval = await client.post(
                f"/workflows/{workflow_id}/approvals",
                json={"decision": "APPROVE"},
            )
            assert plan_approval.status_code == 200
            assignment = plan_approval.json()
            assert assignment["status"] == "WAITING_FOR_AGENT"
            pending = await client.get("/workers/api-worker/assignments")
            assignment_event = pending.json()[0]
            claim = await client.post(
                f"/workers/api-worker/assignments/{assignment_event['event_id']}/claim",
                json={"worker_id": "api-test-worker"},
            )

            completion = await client.post(
                f"/workers/api-worker/assignments/{assignment_event['event_id']}/result",
                json={
                    "worker_id": "api-test-worker",
                    "claim_token": claim.json()["claim_token"],
                    "status": "COMPLETED",
                    "result": {"answer": "done"},
                },
            )
            assert completion.status_code == 200
            assert completion.json()["status"] == "COMPLETED"

            events = await client.get("/events", params={"workflow_id": workflow_id})
            assert events.status_code == 200
            event_types = [event["event_type"] for event in events.json()]
            assert event_types[-1] == "WORKFLOW_COMPLETED"
