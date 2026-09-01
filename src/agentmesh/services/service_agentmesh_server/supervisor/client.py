from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import httpx

from agentmesh.core.models import AssignmentClaim, Event, WorkflowState
from agentmesh.core.models.agent_card import AgentCard


class ControlPlaneGateway:
    """Synchronous HTTP gateway used by the supervisor process."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        service_token: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._service_token = service_token
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def append_event(self, event: Event) -> Event:
        response = self._request(
            "POST", "/internal/events", json=event.model_dump(mode="json")
        )
        return Event.model_validate(response.json())

    def replay(self, workflow_id: UUID) -> list[Event]:
        response = self._request("GET", "/events", params={"workflow_id": str(workflow_id)})
        return [Event.model_validate(item) for item in cast(list[dict[str, Any]], response.json())]

    def get_state(self, workflow_id: UUID) -> WorkflowState:
        response = self._request("GET", f"/state/{workflow_id}")
        return WorkflowState.model_validate(response.json())

    def list_agents(self) -> list[AgentCard]:
        response = self._request("GET", "/registry/agents")
        return [
            AgentCard.model_validate(item)
            for item in cast(list[dict[str, Any]], response.json())
        ]

    def get_agent(self, agent_id: str) -> AgentCard | None:
        response = self._request(
            "GET", f"/registry/agents/{agent_id}", accepted_statuses={200, 404}
        )
        return None if response.status_code == 404 else AgentCard.model_validate(response.json())

    def register(self, card: AgentCard) -> AgentCard:
        response = self._request(
            "PUT", f"/registry/agents/{card.agent_id}", json=card.model_dump(mode="json")
        )
        return AgentCard.model_validate(response.json())

    def heartbeat(self, card: AgentCard, *, runtime_instance_id: str) -> AgentCard:
        response = self._request(
            "POST",
            f"/registry/agents/{card.agent_id}/heartbeat",
            json={
                "agent_id": card.agent_id,
                "agent_version": card.version,
                "runtime_instance_id": runtime_instance_id,
                "runtime_role": "supervisor",
                "runtime_status": "READY",
                "endpoint": card.endpoint,
                "active_task_count": 0,
            },
        )
        return AgentCard.model_validate(response.json())

    def list_actions(self, supervisor_id: str, *, limit: int = 20) -> list[Event]:
        response = self._request(
            "GET", f"/supervisors/{supervisor_id}/actions", params={"limit": limit}
        )
        return [Event.model_validate(item) for item in cast(list[dict[str, Any]], response.json())]

    def claim_action(
        self, supervisor_id: str, action_event_id: UUID, *, worker_id: str
    ) -> AssignmentClaim | None:
        response = self._request(
            "POST",
            f"/supervisors/{supervisor_id}/actions/{action_event_id}/claim",
            json={"worker_id": worker_id},
            accepted_statuses={200, 409},
        )
        if response.status_code == 409:
            return None
        return AssignmentClaim.model_validate(response.json())

    def renew_action(
        self,
        supervisor_id: str,
        action_event_id: UUID,
        *,
        worker_id: str,
        claim_token: UUID,
    ) -> AssignmentClaim:
        response = self._request(
            "POST",
            f"/supervisors/{supervisor_id}/actions/{action_event_id}/renew",
            json={"worker_id": worker_id, "claim_token": str(claim_token)},
        )
        return AssignmentClaim.model_validate(response.json())

    def complete_action(
        self,
        supervisor_id: str,
        action_event_id: UUID,
        *,
        worker_id: str,
        claim_token: UUID,
        result: dict[str, Any],
    ) -> Event:
        response = self._request(
            "POST",
            f"/supervisors/{supervisor_id}/actions/{action_event_id}/complete",
            json={
                "worker_id": worker_id,
                "claim_token": str(claim_token),
                "result": result,
            },
        )
        return Event.model_validate(response.json())

    def fail_action(
        self,
        supervisor_id: str,
        action_event_id: UUID,
        *,
        worker_id: str,
        claim_token: UUID,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_after_seconds: float,
    ) -> Event:
        response = self._request(
            "POST",
            f"/supervisors/{supervisor_id}/actions/{action_event_id}/fail",
            json={
                "worker_id": worker_id,
                "claim_token": str(claim_token),
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
                "retry_after_seconds": retry_after_seconds,
            },
        )
        return Event.model_validate(response.json())

    def _request(
        self,
        method: str,
        path: str,
        *,
        accepted_statuses: set[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if self._service_token:
            headers["X-AgentMesh-Service-Token"] = self._service_token
        response = self._client.request(method, path, headers=headers, **kwargs)
        if response.status_code not in (accepted_statuses or {200, 201, 202}):
            response.raise_for_status()
        return response


class RemoteEventService:
    def __init__(self, gateway: ControlPlaneGateway) -> None:
        self.gateway = gateway

    def append(self, event: Event, *, known_agents: set[str] | None = None) -> Event:
        del known_agents
        return self.gateway.append_event(event)

    def replay(self, workflow_id: UUID) -> list[Event]:
        return self.gateway.replay(workflow_id)


class RemoteStateService:
    def __init__(self, gateway: ControlPlaneGateway) -> None:
        self.gateway = gateway

    def get_current(self, workflow_id: UUID) -> WorkflowState:
        return self.gateway.get_state(workflow_id)


class RemoteRegistryService:
    def __init__(self, gateway: ControlPlaneGateway) -> None:
        self.gateway = gateway

    def list_agents(self) -> list[AgentCard]:
        return self.gateway.list_agents()

    def get_agent(self, agent_id: str) -> AgentCard | None:
        return self.gateway.get_agent(agent_id)
