"""Service compatibility facade for the core PostgreSQL checkpoint adapter."""

from agentmesh.core.database.postgres.checkpoint import create_orchestration_checkpointer

__all__ = ["create_orchestration_checkpointer"]
