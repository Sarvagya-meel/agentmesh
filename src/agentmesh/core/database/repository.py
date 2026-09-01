"""PostgreSQL and in-memory event/claim repositories for AgentMesh."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agentmesh.config import Settings
from agentmesh.core.models.exceptions import ValidationError
from agentmesh.core.models.workflow import AssignmentClaim, Event, EventFilters


class EventRepository(ABC):
    """Persistence contract for the append-only AgentMesh event log."""

    @abstractmethod
    def append(self, event: Event) -> Event:
        """Append an event or return the existing event for the same event ID."""

    @abstractmethod
    def query(self, filters: EventFilters) -> list[Event]:
        """Return matching events in workflow sequence order."""

    @abstractmethod
    def get_by_id(self, event_id: UUID) -> Event | None:
        """Return one event by ID."""

    @abstractmethod
    def list_pending_assignments(self, target_agent: str, *, limit: int = 20) -> list[Event]:
        """Return directed assignments without a terminal result event."""

    @abstractmethod
    def list_pending_supervisor_actions(
        self, target_agent: str, *, limit: int = 20
    ) -> list[Event]:
        """Return supervisor commands without a terminal action event."""


class InMemoryEventRepository(EventRepository):
    """Thread-safe local repository used by the API, UI, and unit tests."""

    def __init__(self) -> None:
        self._events_by_id: dict[UUID, Event] = {}
        self._workflow_events: dict[UUID, list[Event]] = {}
        self._lock = RLock()

    def append(self, event: Event) -> Event:
        with self._lock:
            existing = self._events_by_id.get(event.event_id)
            if existing is not None:
                return existing.model_copy(deep=True)
            workflow_events = self._workflow_events.setdefault(event.workflow_id, [])
            stored = event.model_copy(
                update={"sequence_number": len(workflow_events) + 1}, deep=True
            )
            workflow_events.append(stored)
            self._events_by_id[stored.event_id] = stored
            return stored.model_copy(deep=True)

    def query(self, filters: EventFilters) -> list[Event]:
        with self._lock:
            events = self._workflow_events.get(filters.workflow_id, [])
            matches = [e for e in events if self._matches(e, filters)]
            return [e.model_copy(deep=True) for e in matches[: filters.limit]]

    def get_by_id(self, event_id: UUID) -> Event | None:
        with self._lock:
            event = self._events_by_id.get(event_id)
            return event.model_copy(deep=True) if event is not None else None

    def list_pending_assignments(self, target_agent: str, *, limit: int = 20) -> list[Event]:
        with self._lock:
            terminal_tasks: set[tuple[UUID, str]] = set()
            assignments: list[Event] = []
            for events in self._workflow_events.values():
                for event in events:
                    payload = event.payload if isinstance(event.payload, dict) else {}
                    if event.event_type in {"TASK_COMPLETED", "TASK_FAILED"}:
                        task_id = str(payload.get("task_id", ""))
                        if task_id:
                            terminal_tasks.add((event.workflow_id, task_id))
                    elif event.event_type == "TASK_ASSIGNED" and event.target_agent == target_agent:
                        assignments.append(event)
            pending = []
            for event in sorted(assignments, key=lambda e: e.timestamp):
                payload = event.payload if isinstance(event.payload, dict) else {}
                task = payload.get("task", {})
                task_id = str(task.get("task_id", "")) if isinstance(task, dict) else ""
                if (
                    task_id
                    and (event.workflow_id, task_id) not in terminal_tasks
                    and not self._has_proposed_agent_output(event)
                ):
                    pending.append(event.model_copy(deep=True))
            return pending[:limit]

    def list_pending_supervisor_actions(
        self, target_agent: str, *, limit: int = 20
    ) -> list[Event]:
        with self._lock:
            terminal_action_ids = {
                event.causation_id
                for events in self._workflow_events.values()
                for event in events
                if event.event_type
                in {"SUPERVISOR_ACTION_COMPLETED", "SUPERVISOR_ACTION_FAILED"}
                and event.causation_id is not None
            }
            actions = [
                event.model_copy(deep=True)
                for events in self._workflow_events.values()
                for event in events
                if event.event_type == "SUPERVISOR_ACTION_REQUESTED"
                and event.target_agent == target_agent
                and event.event_id not in terminal_action_ids
            ]
            return sorted(actions, key=lambda event: event.timestamp)[:limit]

    def _has_proposed_agent_output(self, assignment: Event) -> bool:
        events = self._workflow_events.get(assignment.workflow_id, [])
        return any(
            event.event_type in {"AGENT_OUTPUT_PROPOSED", "TASK_OUTPUT_RECEIVED"}
            and event.causation_id == assignment.event_id
            for event in events
        )

    @staticmethod
    def _matches(event: Event, filters: EventFilters) -> bool:
        if filters.since is not None and event.timestamp <= filters.since:
            return False
        if filters.event_type is not None and event.event_type != filters.event_type:
            return False
        if filters.source_agent is not None and event.source_agent != filters.source_agent:
            return False
        return filters.target_agent is None or event.target_agent == filters.target_agent


class PostgresEventRepository(EventRepository):
    """Durable append-only event repository backed by PostgreSQL."""

    def __init__(self, connection: Connection[dict[str, Any]]) -> None:
        self._connection = connection

    @classmethod
    def from_connection_url(cls, connection_url: str) -> PostgresEventRepository:
        connection = psycopg.connect(
            connection_url, autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def append(self, event: Event) -> Event:
        with self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(event.workflow_id),),
            )
            cursor.execute("SELECT * FROM agentmesh_events WHERE event_id = %s", (event.event_id,))
            existing = cursor.fetchone()
            if existing is not None:
                return self._to_event(existing)
            cursor.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_sequence "
                "FROM agentmesh_events WHERE workflow_id = %s",
                (event.workflow_id,),
            )
            sequence_row = cursor.fetchone()
            sequence_number = int(sequence_row["next_sequence"]) if sequence_row else 1
            cursor.execute(
                """
                INSERT INTO agentmesh_events (
                    event_id, conversation_id, workflow_id, timestamp, event_type,
                    source_agent, routing_mode, target_agent, payload, causation_id,
                    causation_chain, routing_weights, metadata, sequence_number
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    event.event_id,
                    event.conversation_id,
                    event.workflow_id,
                    event.timestamp,
                    event.event_type,
                    event.source_agent,
                    str(event.routing_mode),
                    event.target_agent,
                    Jsonb(event.payload),
                    event.causation_id,
                    Jsonb([str(i) for i in event.causation_chain]),
                    Jsonb(event.routing_weights) if event.routing_weights is not None else None,
                    Jsonb(event.metadata),
                    sequence_number,
                ),
            )
            stored = cursor.fetchone()
            if stored is None:
                raise RuntimeError("PostgreSQL did not return the appended event.")
            return self._to_event(stored)

    def query(self, filters: EventFilters) -> list[Event]:
        clauses = ["workflow_id = %s"]
        parameters: list[Any] = [filters.workflow_id]
        if filters.since is not None:
            clauses.append("timestamp > %s")
            parameters.append(filters.since)
        if filters.event_type is not None:
            clauses.append("event_type = %s")
            parameters.append(filters.event_type)
        if filters.source_agent is not None:
            clauses.append("source_agent = %s")
            parameters.append(filters.source_agent)
        if filters.target_agent is not None:
            clauses.append("target_agent = %s")
            parameters.append(filters.target_agent)
        parameters.append(filters.limit)
        sql = (
            "SELECT * FROM agentmesh_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY sequence_number ASC LIMIT %s"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            return [self._to_event(row) for row in cursor.fetchall()]

    def get_by_id(self, event_id: UUID) -> Event | None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM agentmesh_events WHERE event_id = %s", (event_id,))
            row = cursor.fetchone()
            return self._to_event(row) if row is not None else None

    def list_pending_assignments(self, target_agent: str, *, limit: int = 20) -> list[Event]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT assignment.*
                FROM agentmesh_events AS assignment
                WHERE assignment.event_type = 'TASK_ASSIGNED'
                  AND assignment.target_agent = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM agentmesh_events AS result
                    WHERE result.workflow_id = assignment.workflow_id
                      AND result.event_type IN ('TASK_COMPLETED', 'TASK_FAILED')
                      AND result.payload ->> 'task_id' =
                          assignment.payload -> 'task' ->> 'task_id'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM agentmesh_event_claims AS claim
                    WHERE claim.event_id = assignment.event_id
                      AND claim.completed_at IS NULL
                      AND claim.dead_lettered_at IS NULL
                      AND (
                        claim.lease_expires_at > CURRENT_TIMESTAMP
                        OR claim.next_attempt_at > CURRENT_TIMESTAMP
                      )
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM agentmesh_events AS proposed
                    WHERE proposed.workflow_id = assignment.workflow_id
                      AND proposed.event_type IN (
                        'AGENT_OUTPUT_PROPOSED', 'TASK_OUTPUT_RECEIVED'
                      )
                      AND proposed.causation_id = assignment.event_id
                  )
                ORDER BY assignment.timestamp ASC, assignment.sequence_number ASC
                LIMIT %s
                """,
                (target_agent, limit),
            )
            return [self._to_event(row) for row in cursor.fetchall()]

    def list_pending_supervisor_actions(
        self, target_agent: str, *, limit: int = 20
    ) -> list[Event]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT action.*
                FROM agentmesh_events AS action
                WHERE action.event_type = 'SUPERVISOR_ACTION_REQUESTED'
                  AND action.target_agent = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM agentmesh_events AS terminal
                    WHERE terminal.causation_id = action.event_id
                      AND terminal.event_type IN (
                        'SUPERVISOR_ACTION_COMPLETED',
                        'SUPERVISOR_ACTION_FAILED'
                      )
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM agentmesh_event_claims AS claim
                    WHERE claim.event_id = action.event_id
                      AND claim.completed_at IS NULL
                      AND claim.dead_lettered_at IS NULL
                      AND (
                        claim.lease_expires_at > CURRENT_TIMESTAMP
                        OR claim.next_attempt_at > CURRENT_TIMESTAMP
                      )
                  )
                ORDER BY action.timestamp ASC, action.sequence_number ASC
                LIMIT %s
                """,
                (target_agent, limit),
            )
            return [self._to_event(row) for row in cursor.fetchall()]

    @staticmethod
    def _to_event(row: dict[str, Any]) -> Event:
        return Event.model_validate(row)


class ClaimRepository(ABC):
    """Persistence contract for leased assignment ownership."""

    @abstractmethod
    def try_claim(
        self, event_id: UUID, *, agent_id: str, worker_id: str, lease_seconds: int
    ) -> AssignmentClaim | None:
        """Atomically acquire an unclaimed or expired assignment lease."""

    @abstractmethod
    def validate_claim(
        self, event_id: UUID, *, agent_id: str, worker_id: str, claim_token: UUID
    ) -> AssignmentClaim | None:
        """Return an active matching claim, if one exists."""

    @abstractmethod
    def complete(
        self, event_id: UUID, *, agent_id: str, worker_id: str, claim_token: UUID
    ) -> AssignmentClaim | None:
        """Mark an active matching claim completed."""

    @abstractmethod
    def renew(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> AssignmentClaim | None:
        """Extend an active assignment lease."""

    @abstractmethod
    def record_failure(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_after_seconds: float,
    ) -> AssignmentClaim | None:
        """Persist a failed attempt and either schedule retry or dead-letter it."""


class InMemoryClaimRepository(ClaimRepository):
    """Thread-safe leased claim repository for local execution and tests."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._claims: dict[UUID, AssignmentClaim] = {}
        self._lock = RLock()
        self._clock = clock or (lambda: datetime.now(UTC))

    def try_claim(
        self, event_id: UUID, *, agent_id: str, worker_id: str, lease_seconds: int
    ) -> AssignmentClaim | None:
        now = self._clock()
        with self._lock:
            existing = self._claims.get(event_id)
            if existing is not None:
                if existing.completed_at is not None or existing.dead_lettered_at is not None:
                    return None
                if existing.next_attempt_at is not None and existing.next_attempt_at > now:
                    return None
                if existing.lease_expires_at > now:
                    return None
            attempt_number = existing.attempt_number + 1 if existing is not None else 1
            claim = AssignmentClaim(
                event_id=event_id,
                agent_id=agent_id,
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempt_number=attempt_number,
                max_attempts=existing.max_attempts if existing is not None else 3,
                idempotency_key=(
                    existing.idempotency_key if existing is not None else str(uuid4())
                ),
            )
            self._claims[event_id] = claim
            return claim.model_copy(deep=True)

    def validate_claim(
        self, event_id: UUID, *, agent_id: str, worker_id: str, claim_token: UUID
    ) -> AssignmentClaim | None:
        now = self._clock()
        with self._lock:
            claim = self._claims.get(event_id)
            if (
                claim is None
                or claim.completed_at is not None
                or claim.lease_expires_at <= now
                or claim.agent_id != agent_id
                or claim.worker_id != worker_id
                or claim.claim_token != claim_token
            ):
                return None
            return claim.model_copy(deep=True)

    def complete(
        self, event_id: UUID, *, agent_id: str, worker_id: str, claim_token: UUID
    ) -> AssignmentClaim | None:
        with self._lock:
            active = self.validate_claim(
                event_id, agent_id=agent_id, worker_id=worker_id, claim_token=claim_token
            )
            if active is None:
                return None
            completed = active.model_copy(update={"completed_at": self._clock()})
            self._claims[event_id] = completed
            return completed.model_copy(deep=True)

    def renew(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> AssignmentClaim | None:
        with self._lock:
            active = self.validate_claim(
                event_id, agent_id=agent_id, worker_id=worker_id, claim_token=claim_token
            )
            if active is None:
                return None
            renewed = active.model_copy(
                update={"lease_expires_at": self._clock() + timedelta(seconds=lease_seconds)}
            )
            self._claims[event_id] = renewed
            return renewed.model_copy(deep=True)

    def record_failure(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_after_seconds: float,
    ) -> AssignmentClaim | None:
        with self._lock:
            active = self.validate_claim(
                event_id, agent_id=agent_id, worker_id=worker_id, claim_token=claim_token
            )
            if active is None:
                return None
            now = self._clock()
            should_retry = retryable and active.attempt_number < active.max_attempts
            failed = active.model_copy(
                update={
                    "lease_expires_at": now,
                    "next_attempt_at": (
                        now + timedelta(seconds=retry_after_seconds) if should_retry else None
                    ),
                    "last_error_code": error_code,
                    "last_error_message": error_message,
                    "retryable": should_retry,
                    "dead_lettered_at": None if should_retry else now,
                }
            )
            self._claims[event_id] = failed
            return failed.model_copy(deep=True)


class PostgresClaimRepository(ClaimRepository):
    """PostgreSQL-backed claim leases with row-level locking."""

    def __init__(self, connection: Connection[dict[str, Any]]) -> None:
        self._connection = connection

    @classmethod
    def from_connection_url(cls, connection_url: str) -> PostgresClaimRepository:
        connection = psycopg.connect(
            connection_url, autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def try_claim(
        self, event_id: UUID, *, agent_id: str, worker_id: str, lease_seconds: int
    ) -> AssignmentClaim | None:
        now = datetime.now(UTC)
        with self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM agentmesh_event_claims WHERE event_id = %s FOR UPDATE",
                (event_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                existing = AssignmentClaim.model_validate(row)
                if existing.completed_at is not None or existing.dead_lettered_at is not None:
                    return None
                if existing.next_attempt_at is not None and existing.next_attempt_at > now:
                    return None
                if existing.lease_expires_at > now:
                    return None
            attempt_number = existing.attempt_number + 1 if row is not None else 1
            claim = AssignmentClaim(
                event_id=event_id,
                agent_id=agent_id,
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempt_number=attempt_number,
                max_attempts=existing.max_attempts if row is not None else 3,
                idempotency_key=existing.idempotency_key if row is not None else str(uuid4()),
            )
            cursor.execute(
                """
                INSERT INTO agentmesh_event_claims (
                    event_id, agent_id, worker_id, claim_token,
                    claimed_at, lease_expires_at, completed_at,
                    attempt_number, max_attempts, next_attempt_at,
                    last_error_code, last_error_message, retryable,
                    dead_lettered_at, idempotency_key
                ) VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,%s,NULL,NULL,NULL,FALSE,NULL,%s)
                ON CONFLICT (event_id) DO UPDATE SET
                    agent_id = EXCLUDED.agent_id,
                    worker_id = EXCLUDED.worker_id,
                    claim_token = EXCLUDED.claim_token,
                    claimed_at = EXCLUDED.claimed_at,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    completed_at = NULL,
                    attempt_number = EXCLUDED.attempt_number,
                    max_attempts = EXCLUDED.max_attempts,
                    next_attempt_at = NULL,
                    retryable = FALSE,
                    dead_lettered_at = NULL,
                    idempotency_key = EXCLUDED.idempotency_key
                RETURNING *
                """,
                (
                    claim.event_id,
                    claim.agent_id,
                    claim.worker_id,
                    claim.claim_token,
                    claim.claimed_at,
                    claim.lease_expires_at,
                    claim.attempt_number,
                    claim.max_attempts,
                    claim.idempotency_key,
                ),
            )
            stored = cursor.fetchone()
            return AssignmentClaim.model_validate(stored) if stored is not None else None

    def validate_claim(
        self, event_id: UUID, *, agent_id: str, worker_id: str, claim_token: UUID
    ) -> AssignmentClaim | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM agentmesh_event_claims
                WHERE event_id = %s AND agent_id = %s AND worker_id = %s
                  AND claim_token = %s AND completed_at IS NULL
                  AND lease_expires_at > CURRENT_TIMESTAMP
                """,
                (event_id, agent_id, worker_id, claim_token),
            )
            row = cursor.fetchone()
            return AssignmentClaim.model_validate(row) if row is not None else None

    def complete(
        self, event_id: UUID, *, agent_id: str, worker_id: str, claim_token: UUID
    ) -> AssignmentClaim | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE agentmesh_event_claims
                SET completed_at = CURRENT_TIMESTAMP
                WHERE event_id = %s AND agent_id = %s AND worker_id = %s
                  AND claim_token = %s AND completed_at IS NULL
                  AND lease_expires_at > CURRENT_TIMESTAMP
                RETURNING *
                """,
                (event_id, agent_id, worker_id, claim_token),
            )
            row = cursor.fetchone()
            return AssignmentClaim.model_validate(row) if row is not None else None

    def renew(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> AssignmentClaim | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE agentmesh_event_claims
                SET lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                WHERE event_id = %s AND agent_id = %s AND worker_id = %s
                  AND claim_token = %s AND completed_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND lease_expires_at > CURRENT_TIMESTAMP
                RETURNING *
                """,
                (lease_seconds, event_id, agent_id, worker_id, claim_token),
            )
            row = cursor.fetchone()
            return AssignmentClaim.model_validate(row) if row is not None else None

    def record_failure(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_after_seconds: float,
    ) -> AssignmentClaim | None:
        active = self.validate_claim(
            event_id, agent_id=agent_id, worker_id=worker_id, claim_token=claim_token
        )
        if active is None:
            return None
        should_retry = retryable and active.attempt_number < active.max_attempts
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE agentmesh_event_claims
                SET lease_expires_at = CURRENT_TIMESTAMP,
                    next_attempt_at = CASE
                        WHEN %s THEN CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                        ELSE NULL
                    END,
                    last_error_code = %s,
                    last_error_message = %s,
                    retryable = %s,
                    dead_lettered_at = CASE WHEN %s THEN NULL ELSE CURRENT_TIMESTAMP END
                WHERE event_id = %s AND agent_id = %s AND worker_id = %s
                  AND claim_token = %s AND completed_at IS NULL
                RETURNING *
                """,
                (
                    should_retry,
                    retry_after_seconds,
                    error_code,
                    error_message,
                    should_retry,
                    should_retry,
                    event_id,
                    agent_id,
                    worker_id,
                    claim_token,
                ),
            )
            row = cursor.fetchone()
            return AssignmentClaim.model_validate(row) if row is not None else None


def create_event_repository(
    settings: Settings,
) -> tuple[EventRepository, Callable[[], None]]:
    """Create the configured event repository and cleanup callback."""
    backend = settings.event_store_backend.strip().lower()
    if backend == "memory":
        return InMemoryEventRepository(), lambda: None
    if backend != "postgres":
        raise ValidationError("EVENT_STORE_BACKEND must be memory or postgres.")
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    repo = PostgresEventRepository.from_connection_url(url)
    return repo, repo.close


def create_claim_repository(
    settings: Settings,
) -> tuple[ClaimRepository, Callable[[], None]]:
    """Create a claim repository using the configured event-store backend."""
    backend = settings.event_store_backend.strip().lower()
    if backend == "memory":
        return InMemoryClaimRepository(), lambda: None
    if backend != "postgres":
        raise ValidationError("EVENT_STORE_BACKEND must be memory or postgres.")
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    repo = PostgresClaimRepository.from_connection_url(url)
    return repo, repo.close
