from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agentmesh.core.models.agent_card import AgentCard


def normalise_postgres_url(connection_url: str) -> str:
    return connection_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class PostgresResourceRepository:
    """Write resource inventory and audit events for externally running services."""

    def __init__(self, connection: Connection[dict[str, Any]]) -> None:
        self._connection = connection

    @classmethod
    def from_connection_url(cls, connection_url: str) -> PostgresResourceRepository:
        connection = psycopg.connect(
            normalise_postgres_url(connection_url),
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def upsert_agent(
        self,
        card: AgentCard,
        *,
        status: str = "online",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        merged_metadata = dict(card.metadata)
        if metadata:
            merged_metadata.update(metadata)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agentmesh_resources (
                    resource_id, resource_type, name, status, endpoint, owner,
                    capabilities, metadata, registered_at, last_seen, updated_at
                ) VALUES (
                    %s, 'agent', %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (resource_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    endpoint = EXCLUDED.endpoint,
                    owner = EXCLUDED.owner,
                    capabilities = EXCLUDED.capabilities,
                    metadata = agentmesh_resources.metadata || EXCLUDED.metadata,
                    last_seen = EXCLUDED.last_seen,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    card.agent_id,
                    card.name,
                    status,
                    card.endpoint,
                    card.owner,
                    Jsonb(card.capabilities),
                    Jsonb(merged_metadata),
                    card.registered_at,
                    now,
                    now,
                ),
            )

    def upsert_resource(
        self,
        resource_id: str,
        *,
        resource_type: str,
        name: str,
        status: str = "online",
        endpoint: str | None = None,
        owner: str = "platform-team",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_resource_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agentmesh_resources (
                    resource_id, resource_type, name, status, endpoint, owner,
                    capabilities, metadata, parent_resource_id,
                    registered_at, last_seen, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (resource_id) DO UPDATE SET
                    resource_type = EXCLUDED.resource_type,
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    endpoint = EXCLUDED.endpoint,
                    owner = EXCLUDED.owner,
                    capabilities = EXCLUDED.capabilities,
                    metadata = agentmesh_resources.metadata || EXCLUDED.metadata,
                    parent_resource_id = EXCLUDED.parent_resource_id,
                    last_seen = EXCLUDED.last_seen,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    resource_id,
                    resource_type,
                    name,
                    status,
                    endpoint,
                    owner,
                    Jsonb(capabilities or []),
                    Jsonb(metadata or {}),
                    parent_resource_id,
                    now,
                    now,
                    now,
                ),
            )

    def record_audit_event(
        self,
        resource_id: str,
        *,
        event_type: str,
        message: str,
        severity: str = "info",
        actor: str = "system",
        payload: dict[str, Any] | None = None,
        workflow_id: UUID | None = None,
        event_id: UUID | None = None,
    ) -> UUID:
        audit_id = uuid4()
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agentmesh_resource_audit_events (
                    audit_id, resource_id, event_type, severity, actor, message,
                    payload, workflow_id, event_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    audit_id,
                    resource_id,
                    event_type,
                    severity,
                    actor,
                    message,
                    Jsonb(payload or {}),
                    workflow_id,
                    event_id,
                ),
            )
        return audit_id

    def runtime_availability(
        self,
        agent_id: str,
        *,
        stale_seconds: float,
    ) -> dict[str, Any]:
        """Return aggregate availability without copying telemetry into Agent Cards."""

        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, endpoint, metadata
                FROM agentmesh_resources
                WHERE resource_type = 'agent_runtime'
                  AND parent_resource_id = %s
                  AND metadata ->> 'agent_id' = %s
                  AND last_seen >= %s
                  AND status IN ('ready', 'online')
                ORDER BY last_seen DESC
                """,
                (agent_id, agent_id, cutoff),
            )
            rows = cursor.fetchall()
        ready_roles = {
            str(row["metadata"].get("runtime_role", ""))
            for row in rows
            if isinstance(row.get("metadata"), dict)
        }
        direct_ready = bool(ready_roles & {"api", "combined"})
        assignment_ready = bool(ready_roles & {"worker", "combined"})
        direct_endpoint = next(
            (
                str(row["endpoint"])
                for row in rows
                if row.get("endpoint")
                and isinstance(row.get("metadata"), dict)
                and row["metadata"].get("runtime_role") in {"api", "combined"}
            ),
            None,
        )
        return {
            "direct_ready": direct_ready,
            "assignment_ready": assignment_ready,
            "ready_runtime_count": len(rows),
            "ready_runtime_roles": sorted(ready_roles),
            "direct_endpoint": direct_endpoint,
        }

    def mark_stale_runtime_instances(self, *, stale_seconds: float) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE agentmesh_resources
                SET status = 'stale', updated_at = CURRENT_TIMESTAMP
                WHERE resource_type = 'agent_runtime'
                  AND status NOT IN ('offline', 'stale', 'disabled')
                  AND last_seen < %s
                RETURNING resource_id
                """,
                (cutoff,),
            )
            return [str(row["resource_id"]) for row in cursor.fetchall()]
