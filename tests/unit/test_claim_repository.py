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


def test_active_claim_cannot_be_claimed_twice_by_same_worker() -> None:
    repository = InMemoryClaimRepository()
    event_id = uuid4()

    first = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-1",
        lease_seconds=60,
    )
    duplicate = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-1",
        lease_seconds=60,
    )

    assert first is not None
    assert duplicate is None


def test_active_claim_can_be_renewed() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repository = InMemoryClaimRepository(clock=lambda: now)
    event_id = uuid4()
    claim = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-1",
        lease_seconds=30,
    )
    assert claim is not None

    renewed = repository.renew(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-1",
        claim_token=claim.claim_token,
        lease_seconds=90,
    )

    assert renewed is not None
    assert renewed.lease_expires_at == now + timedelta(seconds=90)


def test_retryable_failure_is_delayed_and_increments_attempt() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = [now]
    repository = InMemoryClaimRepository(clock=lambda: current[0])
    event_id = uuid4()
    first = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-1",
        lease_seconds=30,
    )
    assert first is not None

    failed = repository.record_failure(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-1",
        claim_token=first.claim_token,
        error_code="TimeoutError",
        error_message="temporary timeout",
        retryable=True,
        retry_after_seconds=10,
    )
    assert failed is not None
    assert failed.next_attempt_at == now + timedelta(seconds=10)
    assert (
        repository.try_claim(
            event_id,
            agent_id="worker-agent",
            worker_id="worker-2",
            lease_seconds=30,
        )
        is None
    )

    current[0] = now + timedelta(seconds=11)
    second = repository.try_claim(
        event_id,
        agent_id="worker-agent",
        worker_id="worker-2",
        lease_seconds=30,
    )
    assert second is not None
    assert second.attempt_number == 2
    assert second.idempotency_key == first.idempotency_key


def test_final_failed_attempt_is_dead_lettered() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = [now]
    repository = InMemoryClaimRepository(clock=lambda: current[0])
    event_id = uuid4()
    failed = None
    for attempt in range(1, 4):
        claim = repository.try_claim(
            event_id,
            agent_id="worker-agent",
            worker_id=f"worker-{attempt}",
            lease_seconds=30,
        )
        assert claim is not None
        failed = repository.record_failure(
            event_id,
            agent_id="worker-agent",
            worker_id=f"worker-{attempt}",
            claim_token=claim.claim_token,
            error_code="TimeoutError",
            error_message="still unavailable",
            retryable=True,
            retry_after_seconds=10,
        )
        current[0] += timedelta(seconds=11)

    assert failed is not None
    assert failed.dead_lettered_at == now + timedelta(seconds=22)
    assert failed.retryable is False
