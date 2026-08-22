from httpx import ASGITransport, AsyncClient

from agentmesh.services.service_agentmesh_server.app import app


async def test_health_returns_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_heartbeat_requires_matching_runtime_identity() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post(
                "/registry/agents",
                json={"agent_id": "heartbeat-agent", "name": "heartbeat-agent"},
            )
            telemetry = {
                "agent_id": "heartbeat-agent",
                "agent_version": "1.0.0",
                "runtime_instance_id": "runtime-1",
                "runtime_role": "worker",
                "runtime_status": "READY",
            }
            valid = await client.post(
                "/registry/agents/heartbeat-agent/heartbeat",
                json=telemetry,
            )
            mismatched = await client.post(
                "/registry/agents/other-agent/heartbeat",
                json=telemetry,
            )

    assert registered.status_code == 201
    assert valid.status_code == 200
    assert mismatched.status_code == 400
