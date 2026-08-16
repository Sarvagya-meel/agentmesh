from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from agentmesh.agents.base import BaseAgent
from agentmesh.clients.mcp_client import MCPClient
from agentmesh.core.models import Event
from agentmesh.storage.resources import PostgresResourceRepository


class AssignmentWorker:
    """Poll, claim, execute, and report assignments for one agent process."""

    def __init__(
        self,
        agent: BaseAgent,
        client: MCPClient,
        *,
        poll_interval_seconds: float = 2.0,
        heartbeat_seconds: float = 15.0,
        worker_id: str | None = None,
        resource_repository: PostgresResourceRepository | None = None,
    ) -> None:
        self.agent = agent
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_id = worker_id or str(uuid4())
        self.resource_repository = resource_repository
        self._next_heartbeat = datetime.min.replace(tzinfo=UTC)

    def run_once(self) -> bool:
        """Process at most one pending assignment and return whether work ran."""

        self._heartbeat_if_due()
        for assignment in self.client.list_assignments(self.agent.agent_name):
            claim = self.client.claim(
                self.agent.agent_name,
                assignment.event_id,
                worker_id=self.worker_id,
            )
            if claim is None:
                continue
            self._execute_claimed(assignment, claim.claim_token)
            return True
        return False

    def run_forever(self) -> None:
        """Continuously process assignments until the process is interrupted."""

        while True:
            worked = self.run_once()
            if not worked:
                time.sleep(self.poll_interval_seconds)

    def _execute_claimed(self, assignment: Event, claim_token: UUID) -> None:
        task = self._extract_task(assignment)
        status = "COMPLETED"
        self._record_audit(
            "assignment_claimed",
            "Worker claimed an assignment.",
            workflow_id=assignment.workflow_id,
            event_id=assignment.event_id,
            payload={"worker_id": self.worker_id, "task_id": task.get("task_id")},
        )
        try:
            result = self.agent.run_task(task)
        except Exception as exc:
            status = "FAILED"
            result = {"error": str(exc), "error_type": type(exc).__name__}
        self.client.submit_result(
            self.agent.agent_name,
            assignment.event_id,
            worker_id=self.worker_id,
            claim_token=claim_token,
            status=status,
            result=result,
        )
        self._record_audit(
            "assignment_completed" if status == "COMPLETED" else "assignment_failed",
            f"Worker submitted assignment result with status {status}.",
            severity="info" if status == "COMPLETED" else "error",
            workflow_id=assignment.workflow_id,
            event_id=assignment.event_id,
            payload={"worker_id": self.worker_id, "task_id": task.get("task_id")},
        )

    def _heartbeat_if_due(self) -> None:
        now = datetime.now(UTC)
        if now < self._next_heartbeat:
            return
        try:
            self.client.heartbeat(self.agent.agent_name)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422:
                raise
            self.client.register(self.agent.agent_card())
        self._upsert_resource("online")
        self._record_audit(
            "heartbeat",
            "Worker heartbeat recorded.",
            payload={"worker_id": self.worker_id},
        )
        self._next_heartbeat = now + timedelta(seconds=self.heartbeat_seconds)

    def _upsert_resource(self, status: str) -> None:
        if self.resource_repository is None:
            return
        self.resource_repository.upsert_agent(
            self.agent.agent_card(),
            status=status,
            metadata={"worker_id": self.worker_id, "runtime": "docker-or-local"},
        )

    def _record_audit(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
        workflow_id: UUID | None = None,
        event_id: UUID | None = None,
    ) -> None:
        if self.resource_repository is None:
            return
        self.resource_repository.record_audit_event(
            self.agent.agent_name,
            event_type=event_type,
            message=message,
            severity=severity,
            actor=self.worker_id,
            payload=payload,
            workflow_id=workflow_id,
            event_id=event_id,
        )

    @staticmethod
    def _extract_task(assignment: Event) -> dict[str, Any]:
        payload = assignment.payload if isinstance(assignment.payload, dict) else {}
        task = payload.get("task")
        if not isinstance(task, dict):
            raise ValueError(f"Assignment {assignment.event_id} has no task payload.")
        return task
