from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    """Canonical event types used by the AgentMesh event log."""

    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    JOB_DETECTED = "JOB_DETECTED"
    EMAIL_FOUND = "EMAIL_FOUND"
    APPLICATION_SENT = "APPLICATION_SENT"
    AGENT_STATUS = "AGENT_STATUS"


VALID_EVENT_TYPES: frozenset[str] = frozenset(event_type.value for event_type in EventType)
REGISTERED_EVENT_TYPES: tuple[str, ...] = tuple(sorted(VALID_EVENT_TYPES))
