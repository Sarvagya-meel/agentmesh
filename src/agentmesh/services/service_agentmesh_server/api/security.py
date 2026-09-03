from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Request

from agentmesh.config import Settings


def require_internal_service_token(
    request: Request,
    token: Annotated[str | None, Header(alias="X-AgentMesh-Service-Token")] = None,
) -> None:
    """Require the shared service token when one is configured."""

    settings: Settings = request.app.state.settings
    configured = settings.internal_service_token
    if configured is None:
        return
    expected = configured.get_secret_value()
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid internal service token.")
