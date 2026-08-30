from __future__ import annotations

import random
from typing import Any
from uuid import UUID, uuid4

from agentmesh.agents.agent_langgraph_orchestrator_supervisor import MasterOrchestratorAgent
from agentmesh.core.models import AssignmentClaim, Event, RoutingMode
from agentmesh.core.models.exceptions import (
    AgentRegistryError,
    ClaimConflictError,
    ValidationError,
)
from agentmesh.core.observability import (
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
    resolve_trace_author,
    trace_author_metadata,
)
from agentmesh.services.service_agentmesh_server.database.repository import ClaimRepository
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService


class WorkerService:
    """Coordinate assignment discovery, leases, and verified worker results."""

    def __init__(
        self,
        *,
        event_service: EventService,
        claim_repository: ClaimRepository,
        registry_service: RegistryService,
        orchestrator: MasterOrchestratorAgent,
        lease_seconds: int,
    ) -> None:
        self.event_service = event_service
        self.claim_repository = claim_repository
        self.registry_service = registry_service
        self.orchestrator = orchestrator
        self.lease_seconds = lease_seconds

    def list_assignments(self, agent_id: str, *, limit: int = 20) -> list[Event]:
        """Return pending assignments for one currently registered agent."""

        card = self.registry_service.get_agent(agent_id)
        if card is None:
            raise AgentRegistryError(f"Agent {agent_id!r} is not registered.")
        if not self.registry_service.is_assignment_ready(agent_id):
            raise AgentRegistryError(
                f"Agent {agent_id!r} has no ready worker or combined runtime."
            )
        assignments = self.event_service.list_pending_assignments(agent_id, limit=limit)
        if not assignments:
            return assignments
        author = resolve_trace_author(agent_id, agent_card=card)
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                assignments[0].workflow_id,
                "worker list assignments",
                author.author_name,
            ),
            inputs={"agent_id": agent_id, "limit": limit},
            metadata=agentmesh_metadata(
                agent_id=agent_id,
                agent_name=author.author_name,
                workflow_id=assignments[0].workflow_id,
                limit=limit,
                **trace_author_metadata(author),
            ),
            tags=["worker", "assignments", agent_id],
        ) as run:
            if run is not None:
                run.end(outputs={"assignment_count": len(assignments)})
        return assignments

    def submit_directed_assignment(
        self,
        agent_id: str,
        *,
        message: str,
        conversation_id: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a standalone directed task for Agent Playground queue tests."""

        if not self.registry_service.is_assignment_ready(agent_id):
            raise AgentRegistryError(f"Agent {agent_id!r} has no ready worker or combined runtime.")
        workflow_id = uuid4()
        task_id = uuid4()
        resolved_conversation_id = conversation_id or f"playground-{uuid4()}"
        author = resolve_trace_author("agentmesh-control-plane")
        target_author = resolve_trace_author(
            agent_id,
            agent_card=self.registry_service.get_agent(agent_id),
        )
        task: dict[str, Any] = {
            "task_id": str(task_id),
            "description": message,
            "messages": [message],
            "thread_id": thread_id or str(workflow_id),
            "approval_required": False,
            "workflow_id": str(workflow_id),
            "conversation_id": resolved_conversation_id,
        }
        if user_id:
            task["user_id"] = user_id
        assignment = self.event_service.append(
            Event(
                conversation_id=resolved_conversation_id,
                workflow_id=workflow_id,
                event_type="TASK_ASSIGNED",
                source_agent="agentmesh-control-plane",
                routing_mode=RoutingMode.DIRECTED,
                target_agent=agent_id,
                payload={"task": task, "standalone": True},
                metadata={
                    "execution_mode": "queued_direct",
                    **trace_author_metadata(author),
                    "target_agent_name": target_author.author_name,
                },
            )
        )
        return self._directed_snapshot(assignment, "WAITING_FOR_AGENT")

    def claim_assignment(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
    ) -> AssignmentClaim:
        """Validate and atomically lease an assignment to one worker instance."""

        author = resolve_trace_author(
            agent_id,
            agent_card=self.registry_service.get_agent(agent_id),
        )
        with agentmesh_span(
            agentmesh_run_name("WorkFlow", event_id, "assignment claim", author.author_name),
            inputs={"event_id": str(event_id), "agent_id": agent_id, "worker_id": worker_id},
            metadata=agentmesh_metadata(
                event_id=event_id,
                assignment_event_id=event_id,
                agent_id=agent_id,
                agent_name=author.author_name,
                worker_id=worker_id,
                lease_seconds=self.lease_seconds,
                **trace_author_metadata(author),
            ),
            tags=["worker", "claim", agent_id],
        ) as run:
            self._get_assignment(event_id, agent_id=agent_id)
            claim = self.claim_repository.try_claim(
                event_id,
                agent_id=agent_id,
                worker_id=worker_id,
                lease_seconds=self.lease_seconds,
            )
            if claim is None:
                raise ClaimConflictError(f"Assignment {event_id} is already claimed.")
            if run is not None:
                run.end(
                    outputs={
                        "attempt_number": claim.attempt_number,
                        "lease_expires_at": claim.lease_expires_at.isoformat(),
                        "claim_token_present": True,
                    }
                )
            return claim

    async def submit_result(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify claim ownership, resume orchestration, and close the lease."""

        assignment = self._get_assignment(event_id, agent_id=agent_id)
        task = self._task_payload(assignment)
        author = resolve_trace_author(
            agent_id,
            agent_card=self.registry_service.get_agent(agent_id),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                assignment.workflow_id,
                f"assignment result {status}",
                author.author_name,
            ),
            inputs={"status": status, "result_keys": sorted(result)},
            metadata=agentmesh_metadata(
                workflow_id=assignment.workflow_id,
                conversation_id=assignment.conversation_id,
                event_id=event_id,
                assignment_event_id=event_id,
                agent_id=agent_id,
                agent_name=author.author_name,
                worker_id=worker_id,
                task_id=task.get("task_id"),
                claim_token=claim_token,
                **trace_author_metadata(author),
            ),
            tags=["worker", "result", agent_id],
        ) as run:
            response = await self._submit_result_inner(
                assignment,
                task,
                agent_id=agent_id,
                worker_id=worker_id,
                claim_token=claim_token,
                status=status,
                result=result,
            )
            if run is not None:
                run.end(outputs={"workflow_status": response.get("status")})
            return response

    async def _submit_result_inner(
        self,
        assignment: Event,
        task: dict[str, Any],
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        active_claim = self.claim_repository.validate_claim(
            assignment.event_id,
            agent_id=agent_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if active_claim is None:
            raise ClaimConflictError(
                "The assignment claim is missing, expired, or owned elsewhere."
            )

        task_id = UUID(str(task["task_id"]))
        normalized_status = status.strip().upper()
        if normalized_status == "RETRY":
            error_code = str(result.get("error_type", "TRANSIENT_EXECUTION_ERROR"))
            error_message = str(result.get("error", "Agent execution should be retried."))
            base_backoff = min(2**active_claim.attempt_number, 30)
            jitter = random.uniform(0, min(base_backoff * 0.25, 2.0))
            try:
                provider_delay = max(float(result.get("retry_after_seconds", 0) or 0), 0.0)
            except (TypeError, ValueError):
                provider_delay = 0.0
            retry_after_seconds = min(max(base_backoff + jitter, provider_delay), 60)
            failed_claim = self.claim_repository.record_failure(
                assignment.event_id,
                agent_id=agent_id,
                worker_id=worker_id,
                claim_token=claim_token,
                error_code=error_code,
                error_message=error_message,
                retryable=True,
                retry_after_seconds=retry_after_seconds,
            )
            if failed_claim is None:
                raise ClaimConflictError("The assignment failure could not be recorded.")
            if failed_claim.dead_lettered_at is None:
                if self._is_standalone(assignment):
                    return self._directed_snapshot(
                        assignment,
                        "RETRY_SCHEDULED",
                        result={
                            **result,
                            "attempt_number": failed_claim.attempt_number,
                        },
                    )
                return self.orchestrator.get_workflow(assignment.workflow_id)
            if self._is_standalone(assignment):
                normalized_status = "FAILED"
                result = {
                    **result,
                    "dead_lettered": True,
                    "attempt_number": failed_claim.attempt_number,
                }
                return self._complete_standalone(
                    assignment,
                    task,
                    status=normalized_status,
                    result=result,
                    worker_id=worker_id,
                    claim_token=claim_token,
                )
            return await self.orchestrator.asubmit_task_result(
                assignment.workflow_id,
                task_id=task_id,
                assignment_event_id=assignment.event_id,
                status="FAILED",
                result={
                    **result,
                    "dead_lettered": True,
                    "attempt_number": failed_claim.attempt_number,
                },
            )
        if self._is_standalone(assignment):
            return self._complete_standalone(
                assignment,
                task,
                status=normalized_status,
                result=result,
                worker_id=worker_id,
                claim_token=claim_token,
            )
        workflow_result = await self.orchestrator.asubmit_task_result(
            assignment.workflow_id,
            task_id=task_id,
            assignment_event_id=assignment.event_id,
            status=status,
            result=result,
        )
        completed = self.claim_repository.complete(
            assignment.event_id,
            agent_id=agent_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if completed is None:
            raise ClaimConflictError("The assignment lease expired before completion was recorded.")
        return workflow_result

    def _complete_standalone(
        self,
        assignment: Event,
        task: dict[str, Any],
        *,
        status: str,
        result: dict[str, Any],
        worker_id: str,
        claim_token: UUID,
    ) -> dict[str, Any]:
        event_type = "TASK_COMPLETED" if status == "COMPLETED" else "TASK_FAILED"
        terminal = self.event_service.append(
            Event(
                conversation_id=assignment.conversation_id,
                workflow_id=assignment.workflow_id,
                event_type=event_type,
                source_agent=assignment.target_agent or "agentmesh-worker",
                payload={
                    "task_id": str(task["task_id"]),
                    "assignment_event_id": str(assignment.event_id),
                    "status": status,
                    "result": result,
                },
                causation_id=assignment.event_id,
                metadata={"execution_mode": "queued_direct"},
            )
        )
        completed = self.claim_repository.complete(
            assignment.event_id,
            agent_id=assignment.target_agent or "",
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if completed is None:
            raise ClaimConflictError("The assignment lease expired before completion was recorded.")
        return self._directed_snapshot(
            assignment,
            "COMPLETED" if event_type == "TASK_COMPLETED" else "FAILED",
            result={**result, "terminal_event_id": str(terminal.event_id)},
        )

    def renew_claim(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
        claim_token: UUID,
    ) -> AssignmentClaim:
        author = resolve_trace_author(
            agent_id,
            agent_card=self.registry_service.get_agent(agent_id),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                event_id,
                "assignment lease renew",
                author.author_name,
            ),
            inputs={"event_id": str(event_id), "agent_id": agent_id, "worker_id": worker_id},
            metadata=agentmesh_metadata(
                event_id=event_id,
                assignment_event_id=event_id,
                agent_id=agent_id,
                agent_name=author.author_name,
                worker_id=worker_id,
                claim_token=claim_token,
                **trace_author_metadata(author),
            ),
            tags=["worker", "lease", agent_id],
        ) as run:
            self._get_assignment(event_id, agent_id=agent_id)
            renewed = self.claim_repository.renew(
                event_id,
                agent_id=agent_id,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=self.lease_seconds,
            )
            if renewed is None:
                raise ClaimConflictError("The assignment lease cannot be renewed.")
            if run is not None:
                run.end(outputs={"lease_expires_at": renewed.lease_expires_at.isoformat()})
            return renewed

    def _get_assignment(self, event_id: UUID, *, agent_id: str) -> Event:
        event = self.event_service.get_by_id(event_id)
        if event is None or event.event_type != "TASK_ASSIGNED":
            raise ValidationError(f"Assignment event {event_id} was not found.")
        if event.target_agent != agent_id:
            raise AgentRegistryError(
                f"Assignment {event_id} is directed to {event.target_agent!r}, not {agent_id!r}."
            )
        self._task_payload(event)
        return event

    @staticmethod
    def _task_payload(event: Event) -> dict[str, Any]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        task = payload.get("task")
        if not isinstance(task, dict) or not task.get("task_id"):
            raise ValidationError(f"Assignment event {event.event_id} has no valid task payload.")
        return task

    @staticmethod
    def _is_standalone(event: Event) -> bool:
        return isinstance(event.payload, dict) and event.payload.get("standalone") is True

    @staticmethod
    def _directed_snapshot(
        assignment: Event,
        status: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = WorkerService._task_payload(assignment)
        return {
            "workflow_id": str(assignment.workflow_id),
            "conversation_id": assignment.conversation_id,
            "status": status,
            "plan": None,
            "current_task": task,
            "pending_input": None,
            "assigned_agents": [assignment.target_agent] if assignment.target_agent else [],
            "task_results": [result] if result else [],
            "rerun_of_workflow_id": None,
            "rerun_of_task_id": None,
        }
