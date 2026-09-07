"""Backward-compatible settings imports.

New code should import settings from :mod:`agentmesh.core.config`.
"""

from agentmesh.core.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
