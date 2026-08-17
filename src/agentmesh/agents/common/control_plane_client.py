from __future__ import annotations

import time
from typing import Any, cast
from uuid import UUID

import httpx

from agentmesh.core.models import AssignmentClaim, Event
from agentmesh.core.models.agent_card import AgentCard


class ControlPlaneClient:
    """HTTP client used by workers to access registry and assignment APIs."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        retry_attempts: int = 3,
    ) -> None:
        self.retry_attempts = retry_attempts
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    def register(self, card: AgentCard) -> AgentCard:
        response = self._request(
            "PUT",
            f"/registry/agents/{card.agent_id}",
            json=card.model_dump(mode="json"),
        )
        return AgentCard.model_validate(response.json())

    def heartbeat(self, agent_id: str) -> AgentCard:
        response = self._request("POST", f"/registry/agents/{agent_id}/heartbeat")
        return AgentCard.model_validate(response.json())

    def list_assignments(self, agent_id: str, *, limit: int = 20) -> list[Event]:
        response = self._request(
            "GET",
            f"/workers/{agent_id}/assignments",
            params={"limit": limit},
        )
        data = cast(list[dict[str, Any]], response.json())
        return [Event.model_validate(item) for item in data]

    def claim(self, agent_id: str, event_id: UUID, *, worker_id: str) -> AssignmentClaim | None:
        response = self._request(
            "POST",
            f"/workers/{agent_id}/assignments/{event_id}/claim",
            json={"worker_id": worker_id},
            accepted_statuses={200, 409},
        )
        if response.status_code == 409:
            return None
        return AssignmentClaim.model_validate(response.json())

    def submit_result(
        self,
        agent_id: str,
        event_id: UUID,
        *,
        worker_id: str,
        claim_token: UUID,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/workers/{agent_id}/assignments/{event_id}/result",
            json={
                "worker_id": worker_id,
                "claim_token": str(claim_token),
                "status": status,
                "result": result,
            },
        )
        return cast(dict[str, Any], response.json())

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        accepted_statuses: set[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        accepted = accepted_statuses or {200, 201}
        for attempt in range(self.retry_attempts):
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code in accepted:
                    return response
                if response.status_code < 500:
                    response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                if attempt + 1 >= self.retry_attempts:
                    raise
            except httpx.HTTPError:
                if attempt + 1 >= self.retry_attempts:
                    raise
            time.sleep(0.25 * (2**attempt))
        raise RuntimeError("MCP request retry loop exited unexpectedly.")
