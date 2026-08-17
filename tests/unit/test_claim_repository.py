from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agentmesh.services.service_agentmesh_server.database.repository import InMemoryClaimRepository


def test_only_one_worker_claims_an_assignment_concurrently() -> None:
    repository = InMemoryClaimRepository()
    event_id = uuid4()

    def claim(worker_number: int) -> bool:
        return (
            repository.try_claim(
                event_id,
                agent_id="worker-agent",
                worker_id=f"worker-{worker_number}",
                lease_seconds=60,
            )
            is not None
        )

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(claim, range(5)))

    assert results.count(True) == 1


def test_expired_claim_can_be_recovered_after_worker_restart() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = [now]
    repository = InMemoryClaimRepository(clock=lambda: current[0])
    event_id = uuid4()

    first = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="process-before-restart",
        lease_seconds=10,
    )
    assert first is not None

    current[0] = now + timedelta(seconds=11)
    recovered = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="process-after-restart",
        lease_seconds=10,
    )

    assert recovered is not None
    assert recovered.worker_id == "process-after-restart"
    assert recovered.claim_token != first.claim_token
