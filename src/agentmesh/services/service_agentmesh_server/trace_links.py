from __future__ import annotations

from typing import Any

from agentmesh.config import Settings


def resolve_langsmith_trace_link(settings: Settings, request_id: str) -> dict[str, Any]:
    """Resolve a LangSmith UI URL without exposing credentials to the caller."""

    api_key = (
        settings.langsmith_api_key.get_secret_value()
        if settings.langsmith_api_key is not None
        else ""
    )
    if not settings.langsmith_tracing or not api_key:
        return {
            "tracing_enabled": False,
            "available": False,
            "request_id": request_id,
            "reason": "LangSmith tracing is disabled.",
        }

    try:
        from langsmith import Client

        client = Client(
            api_url=settings.langsmith_endpoint,
            api_key=api_key,
            workspace_id=settings.langsmith_workspace_id or None,
            timeout_ms=3000,
        )
        query = (
            'and(eq(metadata_key, "workflow_id"), '
            f'eq(metadata_value, "{request_id}"))'
        )
        run = next(
            client.list_runs(
                project_name=settings.langsmith_project,
                filter=query,
                is_root=True,
                limit=1,
            ),
            None,
        )
        if run is None:
            return {
                "tracing_enabled": True,
                "available": False,
                "request_id": request_id,
                "reason": "The correlated trace has not been ingested yet.",
            }
        return {
            "tracing_enabled": True,
            "available": True,
            "request_id": request_id,
            "url": client.get_run_url(run=run, project_name=settings.langsmith_project),
        }
    except Exception:
        return {
            "tracing_enabled": True,
            "available": False,
            "request_id": request_id,
            "reason": "The LangSmith trace service is temporarily unavailable.",
        }
