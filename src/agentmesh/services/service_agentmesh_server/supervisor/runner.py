from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any
from uuid import UUID

import httpx

from agentmesh.core.models import Event, HumanDecisionType, SupervisorAction, SupervisorActionType
from agentmesh.core.models.exceptions import ModelProviderError, WorkflowConflictError
from agentmesh.services.service_agentmesh_server.orchestration import WorkflowOrchestrator
from agentmesh.services.service_agentmesh_server.supervisor.client import ControlPlaneGateway


class SupervisorActionRunner:
    """Poll, lease, execute, and acknowledge durable supervisor actions."""

    def __init__(
        self,
        *,
        gateway: ControlPlaneGateway,
        orchestrator: WorkflowOrchestrator,
        supervisor_id: str,
        worker_id: str,
        poll_interval_seconds: float,
        lease_seconds: int,
    ) -> None:
        self.gateway = gateway
        self.orchestrator = orchestrator
        self.supervisor_id = supervisor_id
        self.worker_id = worker_id
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_seconds = lease_seconds
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                actions = await asyncio.to_thread(
                    self.gateway.list_actions, self.supervisor_id, limit=20
                )
                for action in actions:
                    if self._stop.is_set():
                        break
                    await self._process(action)
            except (httpx.HTTPError, OSError):
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_seconds)
            except TimeoutError:
                continue

    async def _process(self, event: Event) -> None:
        claim = await asyncio.to_thread(
            self.gateway.claim_action,
            self.supervisor_id,
            event.event_id,
            worker_id=self.worker_id,
        )
        if claim is None:
            return
        renew_task = asyncio.create_task(self._renew_lease(event, claim.claim_token))
        try:
            result = await self.execute(event)
            await asyncio.to_thread(
                self.gateway.complete_action,
                self.supervisor_id,
                event.event_id,
                worker_id=self.worker_id,
                claim_token=claim.claim_token,
                result=result,
            )
        except Exception as exc:
            retryable, retry_after = self.classify_failure(exc, claim.attempt_number)
            with suppress(Exception):
                await asyncio.to_thread(
                    self.gateway.fail_action,
                    self.supervisor_id,
                    event.event_id,
                    worker_id=self.worker_id,
                    claim_token=claim.claim_token,
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:2000] or type(exc).__name__,
                    retryable=retryable,
                    retry_after_seconds=retry_after,
                )
        finally:
            renew_task.cancel()
            with suppress(asyncio.CancelledError):
                await renew_task

    async def execute(self, event: Event) -> dict[str, Any]:
        action = SupervisorAction.model_validate(event.payload)
        arguments = action.arguments
        action_type = SupervisorActionType(action.action_type)
        if action_type == SupervisorActionType.START_WORKFLOW:
            try:
                return await self.orchestrator.astart_workflow(
                    str(arguments["conversation_id"]),
                    str(arguments["goal"]),
                    workflow_id=UUID(str(arguments["workflow_id"])),
                    preferred_agent_ids=list(arguments.get("preferred_agent_ids", [])),
                    rerun_of_workflow_id=self._uuid_or_none(
                        arguments.get("rerun_of_workflow_id")
                    ),
                    rerun_of_task_id=self._uuid_or_none(arguments.get("rerun_of_task_id")),
                    memory_user_id=str(arguments.get("memory_user_id", "")),
                    memory_opt_in=bool(arguments.get("memory_opt_in", False)),
                    memory_updates=dict(arguments.get("memory_updates", {})),
                    memory_delete_keys=list(arguments.get("memory_delete_keys", [])),
                    trace_metadata=dict(arguments.get("trace_metadata", {})),
                )
            except WorkflowConflictError:
                return self.orchestrator.get_workflow(event.workflow_id)
        if action_type == SupervisorActionType.HUMAN_DECISION:
            return await self.orchestrator.asubmit_human_decision(
                UUID(str(arguments["workflow_id"])),
                decision=HumanDecisionType(str(arguments["decision"])),
                feedback=str(arguments.get("feedback", "")),
                actor=str(arguments.get("actor", "human")),
                edits=dict(arguments.get("edits", {})),
            )
        if action_type == SupervisorActionType.TASK_RESULT:
            return await self.orchestrator.asubmit_task_result(
                UUID(str(arguments["workflow_id"])),
                task_id=UUID(str(arguments["task_id"])),
                assignment_event_id=UUID(str(arguments["assignment_event_id"])),
                status=str(arguments["status"]),
                result=dict(arguments.get("result", {})),
            )
        if action_type == SupervisorActionType.RERUN_WORKFLOW:
            return await self.orchestrator.arerun_workflow(UUID(str(arguments["workflow_id"])))
        if action_type == SupervisorActionType.RERUN_TASK:
            return await self.orchestrator.arerun_task(
                UUID(str(arguments["workflow_id"])), UUID(str(arguments["task_id"]))
            )
        if action_type == SupervisorActionType.RECOVER_CHECKPOINT:
            return await self.orchestrator.arecover_checkpoint(
                UUID(str(arguments["source_workflow_id"])),
                checkpoint_id=(
                    str(arguments["checkpoint_id"])
                    if arguments.get("checkpoint_id")
                    else None
                ),
                new_workflow_id=UUID(str(arguments["new_workflow_id"])),
            )
        raise ValueError(f"Unsupported supervisor action {action_type}.")

    async def _renew_lease(self, event: Event, claim_token: UUID) -> None:
        interval = max(self.lease_seconds / 3, 1)
        while True:
            await asyncio.sleep(interval)
            await asyncio.to_thread(
                self.gateway.renew_action,
                self.supervisor_id,
                event.event_id,
                worker_id=self.worker_id,
                claim_token=claim_token,
            )

    @staticmethod
    def classify_failure(exc: Exception, attempt_number: int) -> tuple[bool, float]:
        retryable = isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                ModelProviderError,
            ),
        )
        if isinstance(exc, httpx.HTTPStatusError):
            retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
        lowered = f"{type(exc).__name__} {exc}".lower()
        retryable = retryable or "rate limit" in lowered or "temporar" in lowered
        return retryable, min(float(2**attempt_number), 60.0)

    @staticmethod
    def _uuid_or_none(value: Any) -> UUID | None:
        return UUID(str(value)) if value else None
