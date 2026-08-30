from __future__ import annotations

import os

from agentmesh.config import Settings


def configure_langsmith(settings: Settings) -> None:
    """Make outbound LangSmith tracing an explicit, disabled-by-default choice."""

    api_key = (
        settings.langsmith_api_key.get_secret_value()
        if settings.langsmith_api_key is not None
        else os.environ.get("LANGSMITH_API_KEY", "")
    )
    tracing_enabled = settings.langsmith_tracing and bool(api_key)

    os.environ["LANGSMITH_TRACING"] = "true" if tracing_enabled else "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "true" if tracing_enabled else "false"
    if not tracing_enabled:
        return

    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGCHAIN_API_KEY"] = api_key
    if settings.langsmith_workspace_id:
        os.environ["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id
