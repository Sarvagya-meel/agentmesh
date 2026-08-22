from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from agentmesh.agents.common.control_plane_client import AsyncControlPlaneClient
from agentmesh.agents.common.execution import AgentExecutor, ExecutionContext
from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.core.models import AssignmentClaim, Event

logger = logging.getLogger(__name__)


class AssignmentWorker:
    """Manage runtime presence and consume durable assignments asynchronously."""

    def __init__(
        self,
        executor: AgentExecutor,
        client: AsyncControlPlaneClient,
        *,
        runtime_role: str = "combined",
        poll_interval_seconds: float = 2.0,
        heartbeat_seconds: float = 60.0,
        worker_id: str | None = None,
        runtime_instance_id: str | None = None,
        resource_repository: PostgresResourceRepository | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.executor = executor
        self.agent = executor.agent
        self.client = client
        self.runtime_role = runtime_role
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_id = worker_id or str(uuid4())
        self.runtime_instance_id = runtime_instance_id or str(uuid4())
        self.resource_repository = resource_repository
        self.started_at = datetime.now(UTC)
        self.runtime_status = "STARTING"
        self.max_concurrency = max_concurrency
        self._next_heartbeat = datetime.min.replace(tzinfo=UTC)
        self._registered = False
        self._executions: set[asyncio.Task[None]] = set()
        self._active_assignment_ids: set[UUID] = set()

    @property
    def ready(self) -> bool:
        return self._registered and self.runtime_status == "READY"

    async def start(self) -> None:
        """Register this process before it accepts traffic or assignments."""

        await self._register()
        await self._set_runtime_status("READY", "Agent runtime is ready.")
        await self._send_heartbeat()

    async def stop(self) -> None:
        """Publish draining/offline transitions after active executions drain."""

        if not self._registered:
            return
        for status, message in (
            ("DRAINING", "Agent runtime is draining during shutdown."),
            ("OFFLINE", "Agent runtime shut down cleanly."),
        ):
            await self._set_runtime_status(status, message)
            try:
                await self._send_heartbeat()
            except httpx.HTTPError:
                break
        await self._upsert_resource("offline")

    async def run_once(self, *, consume_assignments: bool = True) -> bool:
        """Refresh presence and schedule at most one claimed assignment."""

        await self._heartbeat_if_due()
        self._discard_completed_executions()
        if not consume_assignments or len(self._executions) >= self.max_concurrency:
            return False

        assignments = await self.client.list_assignments(self.agent.agent_name)
        for assignment in assignments:
            if assignment.event_id in self._active_assignment_ids:
                continue
            claim = await self.client.claim(
                self.agent.agent_name,
                assignment.event_id,
                worker_id=self.worker_id,
            )
            if claim is None:
                continue
            self._active_assignment_ids.add(assignment.event_id)
            execution = asyncio.create_task(
                self._execute_claimed(assignment, claim),
                name=f"{self.agent.agent_name}-assignment-{assignment.event_id}",
            )
            event_id = assignment.event_id

            def release_assignment(_task: asyncio.Future[None], event_id: UUID = event_id) -> None:
                self._active_assignment_ids.discard(event_id)

            execution.add_done_callback(release_assignment)
            self._executions.add(execution)
            return True
        return False

    async def run_forever(
        self,
        stop_event: asyncio.Event,
        *,
        consume_assignments: bool = True,
    ) -> None:
        """Poll until shutdown while keeping the event loop responsive."""

        while not stop_event.is_set():
            try:
                worked = await self.run_once(consume_assignments=consume_assignments)
            except httpx.HTTPError as exc:
                await self._set_runtime_status(
                    "DEGRADED",
                    "Agent runtime lost contact with the control plane.",
                    severity="warning",
                )
                await self._record_audit(
                    "worker_poll_failed",
                    "Runtime could not reach the AgentMesh API and will retry.",
                    severity="warning",
                    payload={"worker_id": self.worker_id, "error": str(exc)},
                )
                worked = False
            else:
                if self.runtime_status == "DEGRADED":
                    await self._set_runtime_status(
                        "READY",
                        "Agent runtime recovered control-plane connectivity.",
                    )
                    self._next_heartbeat = datetime.min.replace(tzinfo=UTC)
            if not worked:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)
                except TimeoutError:
                    pass

        if self._executions:
            await asyncio.gather(*self._executions, return_exceptions=True)

    async def _execute_claimed(self, assignment: Event, claim: AssignmentClaim) -> None:
        task = self._extract_task(assignment)
        status = "COMPLETED"
        await self._record_audit(
            "assignment_claimed",
            "Worker claimed an assignment.",
            workflow_id=assignment.workflow_id,
            event_id=assignment.event_id,
            payload={"worker_id": self.worker_id, "task_id": task.get("task_id")},
        )
        lease_seconds = max(
            (claim.lease_expires_at - claim.claimed_at).total_seconds(),
            3.0,
        )
        renewal_stop = asyncio.Event()
        renewal_task = asyncio.create_task(
            self._renew_lease(
                assignment,
                claim,
                renewal_stop,
                lease_seconds / 3,
            ),
            name=f"{self.agent.agent_name}-lease-{assignment.event_id}",
        )
        try:
            context = ExecutionContext(
                source="assignment",
                thread_id=str(task.get("thread_id") or assignment.workflow_id),
                workflow_id=str(assignment.workflow_id),
                assignment_id=str(assignment.event_id),
                attempt_number=claim.attempt_number,
            )
            result = await self.executor.execute(task, context)
            result.setdefault("attempt_number", claim.attempt_number)
            result_status = str(result.get("status", "COMPLETED")).strip().upper()
            if result_status in {"AWAITING_APPROVAL", "REJECTED"}:
                status = result_status
        except Exception as exc:
            status = "RETRY" if self._is_retryable_failure(exc) else "FAILED"
            result = {"error": str(exc), "error_type": type(exc).__name__}
            retry_after_seconds = self._retry_after_seconds(exc)
            if retry_after_seconds is not None:
                result["retry_after_seconds"] = retry_after_seconds
        finally:
            renewal_stop.set()
            await renewal_task

        await self.client.submit_result(
            self.agent.agent_name,
            assignment.event_id,
            worker_id=self.worker_id,
            claim_token=claim.claim_token,
            status=status,
            result=result,
        )
        await self._record_audit(
            self._result_audit_type(status),
            f"Worker submitted assignment result with status {status}.",
            severity="error" if status == "FAILED" else "info",
            workflow_id=assignment.workflow_id,
            event_id=assignment.event_id,
            payload={"worker_id": self.worker_id, "task_id": task.get("task_id")},
        )

    async def _renew_lease(
        self,
        assignment: Event,
        claim: AssignmentClaim,
        stop_event: asyncio.Event,
        interval_seconds: float,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                return
            except TimeoutError:
                pass
            try:
                await self.client.renew(
                    self.agent.agent_name,
                    assignment.event_id,
                    worker_id=self.worker_id,
                    claim_token=claim.claim_token,
                )
            except httpx.HTTPError as exc:
                await self._record_audit(
                    "assignment_lease_renewal_failed",
                    "Worker could not renew the active assignment lease.",
                    severity="warning",
                    workflow_id=assignment.workflow_id,
                    event_id=assignment.event_id,
                    payload={"error": str(exc), "worker_id": self.worker_id},
                )
                return

    async def _heartbeat_if_due(self) -> None:
        now = datetime.now(UTC)
        if now < self._next_heartbeat:
            return
        try:
            if self._registered:
                await self._send_heartbeat()
            else:
                await self._register()
                await self._set_runtime_status("READY", "Agent runtime registered.")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            self._registered = False
            await self._register()
            await self._set_runtime_status(
                "READY", "Agent runtime re-registered after registry state was lost."
            )
            await self._send_heartbeat()
        await self._upsert_resource(self.runtime_status.lower())
        self._next_heartbeat = now + timedelta(seconds=self.heartbeat_seconds)

    async def _register(self) -> None:
        card_status = "starting" if self.runtime_status == "STARTING" else "online"
        card = self.agent.agent_card().model_copy(
            update={
                "status": card_status,
                "metadata": {
                    **self.agent.metadata,
                    "runtime_model": "multi-instance",
                },
            }
        )
        await self.client.register(card)
        self._registered = True
        await self._upsert_resource(card_status)
        await self._record_audit(
            "agent_registered",
            "Agent runtime registered with the control plane.",
            payload=self._telemetry(),
        )

    async def _send_heartbeat(self) -> None:
        await self.client.heartbeat(self.agent.agent_name, self._telemetry())

    def _telemetry(self) -> dict[str, Any]:
        card = self.agent.agent_card()
        return {
            "agent_id": self.agent.agent_name,
            "agent_version": card.version,
            "runtime_instance_id": self.runtime_instance_id,
            "runtime_role": self.runtime_role,
            "runtime_status": self.runtime_status,
            "endpoint": self.agent.endpoint,
            "active_task_count": self.executor.active_count,
            "started_at": self.started_at.isoformat(),
            "last_successful_model_call": getattr(self.agent, "last_successful_model_call", None),
        }

    async def _set_runtime_status(
        self,
        status: str,
        message: str,
        *,
        severity: str = "info",
    ) -> None:
        if self.runtime_status == status:
            return
        previous = self.runtime_status
        self.runtime_status = status
        await self._record_audit(
            "agent_status_changed",
            message,
            severity=severity,
            payload={
                "runtime_instance_id": self.runtime_instance_id,
                "previous_status": previous,
                "status": status,
            },
        )
        await self._upsert_resource(status.lower())

    async def _upsert_resource(self, status: str) -> None:
        if self.resource_repository is None:
            return
        card = self.agent.agent_card()
        runtime_resource_id = f"agent:{self.agent.agent_name}:runtime:{self.runtime_instance_id}"
        await asyncio.to_thread(
            self.resource_repository.upsert_agent,
            card,
            status="online" if status in {"ready", "online"} else status,
            metadata={"runtime_model": "multi-instance"},
        )
        await asyncio.to_thread(
            self.resource_repository.upsert_resource,
            runtime_resource_id,
            resource_type="agent_runtime",
            name=f"{self.agent.agent_name}-{self.runtime_role}",
            status=status,
            endpoint=self.agent.endpoint,
            owner=card.owner,
            capabilities=card.capabilities,
            metadata={"worker_id": self.worker_id, **self._telemetry()},
            parent_resource_id=self.agent.agent_name,
        )

    async def _record_audit(
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
        runtime_resource_id = f"agent:{self.agent.agent_name}:runtime:{self.runtime_instance_id}"
        await asyncio.to_thread(
            self.resource_repository.record_audit_event,
            runtime_resource_id,
            event_type=event_type,
            message=message,
            severity=severity,
            actor=self.worker_id,
            payload=payload,
            workflow_id=workflow_id,
            event_id=event_id,
        )

    def _discard_completed_executions(self) -> None:
        completed = {task for task in self._executions if task.done()}
        for task in completed:
            exception = task.exception()
            if exception is not None:
                logger.error(
                    "Assignment execution task failed outside the agent execution boundary.",
                    exc_info=(type(exception), exception, exception.__traceback__),
                )
        self._executions.difference_update(completed)

    @staticmethod
    def _result_audit_type(status: str) -> str:
        return {
            "AWAITING_APPROVAL": "assignment_waiting_approval",
            "COMPLETED": "assignment_completed",
            "REJECTED": "assignment_rejected",
            "RETRY": "assignment_retry_scheduled",
        }.get(status, "assignment_failed")

    @staticmethod
    def _is_retryable_failure(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        if getattr(exc, "retryable", False) is True:
            return True
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and (status_code == 429 or status_code >= 500):
            return True
        return type(exc).__name__.lower() in {
            "ratelimiterror",
            "serviceunavailableerror",
            "apiconnectionerror",
            "apitimeouterror",
        }

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float | None:
        direct_value = getattr(exc, "retry_after_seconds", None)
        if isinstance(direct_value, (int, float)):
            return max(float(direct_value), 0.0)
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            raw_header = headers.get("retry-after")
            if raw_header is not None:
                try:
                    return max(float(raw_header), 0.0)
                except (TypeError, ValueError):
                    pass
        match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
        return max(float(match.group(1)), 0.0) if match else None

    @staticmethod
    def _extract_task(assignment: Event) -> dict[str, Any]:
        payload = assignment.payload if isinstance(assignment.payload, dict) else {}
        task = payload.get("task")
        if not isinstance(task, dict):
            raise ValueError(f"Assignment {assignment.event_id} has no task payload.")
        return task
