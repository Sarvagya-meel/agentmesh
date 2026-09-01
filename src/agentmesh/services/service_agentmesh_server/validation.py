from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from agentmesh.core.models import Event, ValidationDecision
from agentmesh.services.service_agentmesh_server.events.service import EventService


class TaskOutputValidator:
    """Persist raw output and deterministic validation before supervisor use."""

    def __init__(self, event_service: EventService) -> None:
        self.event_service = event_service

    def validate(
        self,
        assignment: Event,
        *,
        task_id: UUID,
        status: str,
        result: dict[str, Any],
    ) -> ValidationDecision:
        canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
        output_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        normalized_status = status.strip().upper()
        checks = {
            "status_supported": normalized_status in {"COMPLETED", "AWAITING_APPROVAL"},
            "result_is_object": isinstance(result, dict),
            "result_not_empty": bool(result),
            "no_error_marker": not bool(result.get("error")),
            "approval_has_thread": (
                normalized_status != "AWAITING_APPROVAL" or bool(result.get("thread_id"))
            ),
        }
        valid = all(checks.values())
        reasons = [name for name, passed in checks.items() if not passed]
        received_id = uuid5(assignment.event_id, f"output:{output_hash}")
        received = self.event_service.append(
            Event(
                event_id=received_id,
                conversation_id=assignment.conversation_id,
                workflow_id=assignment.workflow_id,
                event_type="TASK_OUTPUT_RECEIVED",
                source_agent=assignment.target_agent or "agentmesh-worker",
                payload={
                    "task_id": str(task_id),
                    "assignment_event_id": str(assignment.event_id),
                    "status": normalized_status,
                    "result": result,
                    "output_hash": output_hash,
                },
                causation_id=assignment.event_id,
                metadata={"validation_stage": "received"},
            )
        )
        requested = self.event_service.append(
            Event(
                event_id=uuid5(received_id, "validation-requested"),
                conversation_id=assignment.conversation_id,
                workflow_id=assignment.workflow_id,
                event_type="TASK_VALIDATION_REQUESTED",
                source_agent="agentmesh-control-plane",
                payload={
                    "task_id": str(task_id),
                    "assignment_event_id": str(assignment.event_id),
                    "output_hash": output_hash,
                },
                causation_id=received.event_id,
            )
        )
        decision = ValidationDecision(
            workflow_id=assignment.workflow_id,
            task_id=task_id,
            assignment_event_id=assignment.event_id,
            output_hash=output_hash,
            valid=valid,
            checks=checks,
            reasons=reasons,
        )
        self.event_service.append(
            Event(
                event_id=uuid5(received_id, "validation-completed"),
                conversation_id=assignment.conversation_id,
                workflow_id=assignment.workflow_id,
                event_type="TASK_VALIDATION_COMPLETED",
                source_agent="agentmesh-control-plane",
                payload={"decision": decision.model_dump(mode="json")},
                causation_id=requested.event_id,
                metadata={"validation_stage": "deterministic"},
            )
        )
        return decision
