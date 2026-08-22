from __future__ import annotations

import os

from agentmesh.config import Settings


def configure_langsmith(settings: Settings) -> None:
    """Make outbound LangSmith tracing an explicit, disabled-by-default choice."""

    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    if settings.langsmith_tracing:
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
