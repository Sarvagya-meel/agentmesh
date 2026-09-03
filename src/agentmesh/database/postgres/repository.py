"""PostgreSQL repository adapters for AgentMesh."""

from agentmesh.services.service_agentmesh_server.database.repository import (
    ClaimRepository,
    EventRepository,
    InMemoryClaimRepository,
    InMemoryEventRepository,
    PostgresClaimRepository,
    PostgresEventRepository,
    create_claim_repository,
    create_event_repository,
)

__all__ = [
    "ClaimRepository",
    "EventRepository",
    "InMemoryClaimRepository",
    "InMemoryEventRepository",
    "PostgresClaimRepository",
    "PostgresEventRepository",
    "create_claim_repository",
    "create_event_repository",
]

# TODO: Remove this shim after callers import the core repository module directly.
