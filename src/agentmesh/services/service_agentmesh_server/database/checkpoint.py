"""Backward-compatibility shim — real implementation is in core.database.checkpoint."""

from agentmesh.core.database.checkpoint import create_orchestration_checkpointer

__all__ = ["create_orchestration_checkpointer"]
