"""Backward-compatibility shim — real implementation is in core.database.repository."""

from agentmesh.core.database.repository import (
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
