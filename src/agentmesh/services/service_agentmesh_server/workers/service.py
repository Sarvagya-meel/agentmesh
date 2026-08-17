from __future__ import annotations

from typing import Any
from uuid import UUID

from agentmesh.agents.agent_langgraph_orchestrator_supervisor import MasterOrchestratorAgent
from agentmesh.core.models import AssignmentClaim, Event
from agentmesh.core.models.exceptions import (
    AgentRegistryError,
    ClaimConflictError,
    ValidationError,
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
        if card.status != "online":
            raise AgentRegistryError(f"Agent {agent_id!r} is not online.")
        return self.event_service.list_pending_assignments(agent_id, limit=limit)

    def claim_assignment(
        self,
        event_id: UUID,
        *,
        agent_id: str,
        worker_id: str,
    ) -> AssignmentClaim:
        """Validate and atomically lease an assignment to one worker instance."""

        self._get_assignment(event_id, agent_id=agent_id)
        claim = self.claim_repository.try_claim(
            event_id,
            agent_id=agent_id,
            worker_id=worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            raise ClaimConflictError(f"Assignment {event_id} is already claimed.")
        return claim

    def submit_result(
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
        active_claim = self.claim_repository.validate_claim(
            event_id,
            agent_id=agent_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if active_claim is None:
            raise ClaimConflictError(
                "The assignment claim is missing, expired, or owned elsewhere."
            )

        task = self._task_payload(assignment)
        task_id = UUID(str(task["task_id"]))
        workflow_result = self.orchestrator.submit_task_result(
            assignment.workflow_id,
            task_id=task_id,
            assignment_event_id=assignment.event_id,
            status=status,
            result=result,
        )
        completed = self.claim_repository.complete(
            event_id,
            agent_id=agent_id,
            worker_id=worker_id,
            claim_token=claim_token,
        )
        if completed is None:
            raise ClaimConflictError("The assignment lease expired before completion was recorded.")
        return workflow_result

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
