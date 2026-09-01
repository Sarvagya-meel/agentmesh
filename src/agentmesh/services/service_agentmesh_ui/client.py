from __future__ import annotations

from typing import Any, TypeAlias, cast

import httpx

JsonObject: TypeAlias = dict[str, Any]


class ControlPlaneClient:
    """HTTP-only gateway used by Streamlit and its tests."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def list_agents(self) -> list[JsonObject]:
        return self._list("/registry/agents")

    def list_resources(self, *, limit: int = 100) -> list[JsonObject]:
        return self._list("/registry/resources", params={"limit": limit})

    def list_audit_events(self, *, limit: int = 100) -> list[JsonObject]:
        return self._list("/registry/audit-events", params={"limit": limit})

    def invoke_agent(self, card: JsonObject, message: str) -> JsonObject:
        endpoint = str(card.get("endpoint", "")).rstrip("/")
        if not endpoint:
            raise ValueError(f"Agent {card.get('agent_id', 'unknown')!r} has no endpoint.")
        return self._external_post(
            f"{endpoint}/invoke",
            {
                "message": message,
                "approval_required": card.get("agent_id") == "langgraph-copilot",
            },
        )

    def resume_agent(self, card: JsonObject, thread_id: str, decision: str) -> JsonObject:
        endpoint = str(card.get("endpoint", "")).rstrip("/")
        if not endpoint:
            raise ValueError(f"Agent {card.get('agent_id', 'unknown')!r} has no endpoint.")
        return self._external_post(
            f"{endpoint}/conversations/{thread_id}/resume",
            {"decision": decision},
        )

    def submit_assignment(self, agent_id: str, message: str, conversation_id: str) -> JsonObject:
        return self._post(
            f"/workers/{agent_id}/assignments",
            {"message": message, "conversation_id": conversation_id},
        )

    def start_workflow(
        self, goal: str, preferred_agent_ids: list[str], conversation_id: str
    ) -> JsonObject:
        return self._post(
            "/workflows/start",
            {
                "conversation_id": conversation_id,
                "goal": goal,
                "preferred_agent_ids": preferred_agent_ids,
            },
        )

    def workflow_activity(
        self, workflow_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> JsonObject:
        return self._get(
            f"/workflows/{workflow_id}/activity",
            params={"after_sequence": after_sequence, "limit": limit},
        )

    def submit_approval(
        self, workflow_id: str, decision: str, *, feedback: str = ""
    ) -> JsonObject:
        return self._post(
            f"/workflows/{workflow_id}/approvals",
            {
                "decision": decision.upper(),
                "feedback": feedback,
                "actor": "streamlit-user",
                "edits": {},
            },
        )

    def checkpoints(self, workflow_id: str) -> list[JsonObject]:
        return self._list(f"/workflows/{workflow_id}/checkpoints")

    def replay_checkpoint(self, workflow_id: str, checkpoint_id: str) -> JsonObject:
        return self._post(
            f"/workflows/{workflow_id}/replay", {"checkpoint_id": checkpoint_id}
        )

    def recover_checkpoint(
        self, workflow_id: str, checkpoint_id: str | None = None
    ) -> JsonObject:
        return self._post(
            f"/workflows/{workflow_id}/recover",
            {"checkpoint_id": checkpoint_id, "new_workflow_id": None},
        )

    def rerun_workflow(self, workflow_id: str) -> JsonObject:
        return self._post(f"/workflows/{workflow_id}/rerun", {})

    def rerun_task(self, workflow_id: str, task_id: str) -> JsonObject:
        return self._post(f"/workflows/{workflow_id}/tasks/{task_id}/rerun", {})

    def trace_link(self, workflow_id: str) -> JsonObject:
        return self._get(f"/workflows/{workflow_id}/trace-link")

    def _get(self, path: str, **kwargs: Any) -> JsonObject:
        response = httpx.get(
            f"{self.base_url}{path}", timeout=self.timeout_seconds, **kwargs
        )
        response.raise_for_status()
        return cast(JsonObject, response.json())

    def _post(self, path: str, body: JsonObject) -> JsonObject:
        response = httpx.post(
            f"{self.base_url}{path}", json=body, timeout=self.timeout_seconds
        )
        response.raise_for_status()
        return cast(JsonObject, response.json())

    def _list(self, path: str, **kwargs: Any) -> list[JsonObject]:
        response = httpx.get(
            f"{self.base_url}{path}", timeout=self.timeout_seconds, **kwargs
        )
        response.raise_for_status()
        return cast(list[JsonObject], response.json())

    def _external_post(self, url: str, body: JsonObject) -> JsonObject:
        response = httpx.post(url, json=body, timeout=self.timeout_seconds)
        response.raise_for_status()
        return cast(JsonObject, response.json())
