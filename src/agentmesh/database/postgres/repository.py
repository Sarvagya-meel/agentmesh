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

# TODO next fixes remove this file and make reference to original module at src/agentmesh/core/database/repository.py