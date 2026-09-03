from __future__ import annotations

from typing import Any
from uuid import UUID

from agentmesh.core.models import (
    AssignmentClaim,
    Event,
    RoutingMode,
    SupervisorAction,
    SupervisorActionType,
)
from agentmesh.core.models.exceptions import ClaimConflictError, ValidationError
from agentmesh.services.service_agentmesh_server.database.repository import ClaimRepository
from agentmesh.services.service_agentmesh_server.events.service import EventService


class SupervisorActionService:
    """Durable command queue connecting the control plane to a supervisor."""

    def __init__(
        self,
        *,
        event_service: EventService,
        claim_repository: ClaimRepository,
        lease_seconds: int,
    ) -> None:
        self.event_service = event_service
        self.claim_repository = claim_repository
        self.lease_seconds = lease_seconds

    def enqueue(
        self,
        *,
        conversation_id: str,
        workflow_id: UUID,
        action_type: SupervisorActionType | str,
        arguments: dict[str, Any],
        supervisor_id: str,
        action_event_id: UUID | None = None,
    ) -> Event:
        action = SupervisorAction(action_type=action_type, arguments=arguments)
        values: dict[str, Any] = {
            "conversation_id": conversation_id,
            "workflow_id": workflow_id,
            "event_type": "SUPERVISOR_ACTION_REQUESTED",
            "source_agent": "agentmesh-control-plane",
            "routing_mode": RoutingMode.DIRECTED,
            "target_agent": supervisor_id,
            "payload": action.model_dump(mode="json"),
            "metadata": {"queue": "supervisor-actions", "schema_version": 1},
        }
        if action_event_id is not None:
            values["event_id"] = action_event_id
        return self.event_service.append(Event.model_validate(values))

    def list_actions(self, supervisor_id: str, *, limit: int = 20) -> list[Event]:
        return self.event_service.list_pending_supervisor_actions(supervisor_id, limit=limit)

    def claim(
        self, action_event_id: UUID, *, supervisor_id: str, worker_id: str
    ) -> AssignmentClaim:
        self._get_action(action_event_id, supervisor_id=supervisor_id)
        claim = self.claim_repository.try_claim(
            action_event_id,
            agent_id=supervisor_id,
            worker_id=worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            raise ClaimConflictError(f"Supervisor action {action_event_id} is already claimed.")
        return claim

    def renew(
        self,
        action_event_id: UUID,
        *,
        supervisor_id: str,
        worker_id: str,
        claim_token: UUID,
    ) -> AssignmentClaim:
        self._get_action(action_event_id, supervisor_id=supervisor_id)
        claim = self.claim_repository.renew(
            action_event_id,
            agent_id=supervisor_id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            raise ClaimConflictError("The supervisor action lease cannot be renewed.")
        return claim

    def complete(
        self,
        action_event_id: UUID,
        *,
        supervisor_id: str,
        worker_id: str,
        claim_token: UUID,
        result: dict[str, Any],
    ) -> Event:
        action = self._get_action(action_event_id, supervisor_id=supervisor_id)
        self._require_active_claim(
            action_event_id,
            supervisor_id=supervisor_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        terminal = self.event_service.append(
            Event(
                conversation_id=action.conversation_id,
                workflow_id=action.workflow_id,
                event_type="SUPERVISOR_ACTION_COMPLETED",
                source_agent=supervisor_id,
                payload={"action_event_id": str(action_event_id), "result": result},
                causation_id=action_event_id,
                metadata={"queue": "supervisor-actions", "worker_id": worker_id},
            )
        )
        completed = self.claim_repository.complete(
            action_event_id,
            agent_id=supervisor_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if completed is None:
            raise ClaimConflictError("The action lease expired before completion was recorded.")
        return terminal

    def fail(
        self,
        action_event_id: UUID,
        *,
        supervisor_id: str,
        worker_id: str,
        claim_token: UUID,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_after_seconds: float,
    ) -> Event:
        action = self._get_action(action_event_id, supervisor_id=supervisor_id)
        failed_claim = self.claim_repository.record_failure(
            action_event_id,
            agent_id=supervisor_id,
            worker_id=worker_id,
            claim_token=claim_token,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )
        if failed_claim is None:
            raise ClaimConflictError("The supervisor action failure could not be recorded.")
        event_type = (
            "SUPERVISOR_ACTION_RETRY_SCHEDULED"
            if failed_claim.dead_lettered_at is None
            else "SUPERVISOR_ACTION_FAILED"
        )
        return self.event_service.append(
            Event(
                conversation_id=action.conversation_id,
                workflow_id=action.workflow_id,
                event_type=event_type,
                source_agent=supervisor_id,
                payload={
                    "action_event_id": str(action_event_id),
                    "error_code": error_code,
                    "error_message": error_message,
                    "retryable": failed_claim.retryable,
                    "attempt_number": failed_claim.attempt_number,
                    "next_attempt_at": (
                        failed_claim.next_attempt_at.isoformat()
                        if failed_claim.next_attempt_at is not None
                        else None
                    ),
                },
                causation_id=action_event_id,
                metadata={"queue": "supervisor-actions", "worker_id": worker_id},
            )
        )

    def _get_action(self, action_event_id: UUID, *, supervisor_id: str) -> Event:
        action = self.event_service.get_by_id(action_event_id)
        if action is None or action.event_type != "SUPERVISOR_ACTION_REQUESTED":
            raise ValidationError(f"Supervisor action {action_event_id} was not found.")
        if action.target_agent != supervisor_id:
            raise ValidationError(
                f"Supervisor action {action_event_id} targets {action.target_agent!r}."
            )
        SupervisorAction.model_validate(action.payload)
        return action

    def _require_active_claim(
        self,
        action_event_id: UUID,
        *,
        supervisor_id: str,
        worker_id: str,
        claim_token: UUID,
    ) -> AssignmentClaim:
        claim = self.claim_repository.validate_claim(
            action_event_id,
            agent_id=supervisor_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if claim is None:
            raise ClaimConflictError("The supervisor action claim is missing, expired, or stale.")
        return claim
