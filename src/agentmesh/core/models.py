from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.core.event_types import VALID_EVENT_TYPES
from agentmesh.core.exceptions import (
    AgentRegistryError,
    CausationLoopError,
    InvalidEventTypeError,
    InvalidRoutingError,
    InvalidWorkflowIdError,
    ValidationError,
)

JsonPrimitive: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None


class RoutingMode(str, Enum):
    """Supported routing modes for event dispatch."""

    DIRECTED = "DIRECTED"
    FANOUT = "FANOUT"
    CLAIMED = "CLAIMED"


class WorkflowStatus(str, Enum):
    """Lifecycle statuses for a workflow."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _normalise_string(value: str | None, *, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def validate_workflow_id(workflow_id: str | UUID, *, require_v4: bool = True) -> UUID:
    """Validate a workflow UUID and optionally enforce UUIDv4 semantics."""

    try:
        parsed = UUID(str(workflow_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidWorkflowIdError(f"Invalid workflow_id: {workflow_id!r}.") from exc

    if require_v4 and parsed.version != 4:
        raise InvalidWorkflowIdError("workflow_id must be a valid UUID v4.")

    return parsed


def validate_conversation_id(conversation_id: str | None) -> str:
    """Validate a conversation identifier; non-empty values only."""

    return _normalise_string(conversation_id, field_name="conversation_id")


def validate_agent_name(agent_name: str | None, *, field_name: str = "agent_name") -> str:
    """Validate an agent identifier used by routing or registry checks."""

    return _normalise_string(agent_name, field_name=field_name)


def validate_agent_registry(agent_name: str | None, *, known_agents: set[str] | None = None) -> str:
    """Validate source/target agents against a caller-supplied registry snapshot."""

    cleaned = validate_agent_name(agent_name, field_name="source_agent")
    registry = {"orchestrator", *(known_agents or set())}
    if known_agents is not None and cleaned not in registry:
        raise AgentRegistryError(f"Unknown agent {cleaned!r}; not in registry.")
    return cleaned


def validate_json_payload(payload: Any) -> Any:
    """Ensure an event payload is JSON-serialisable."""

    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ValidationError("payload must be JSON-serializable.") from exc
    return payload


def validate_causation_chain(entries: list[str | UUID] | tuple[str | UUID, ...] | None) -> list[UUID]:
    """Transform and validate a causation chain without allowing cycles."""

    if entries is None:
        return []

    parsed: list[UUID] = []
    seen: set[UUID] = set()
    for item in entries:
        value = UUID(str(item))
        if value in seen:
            raise CausationLoopError("causation_chain contains duplicate event identifiers.")
        seen.add(value)
        parsed.append(value)

    return parsed


class Event(BaseModel):
    """Canonical event representation used throughout AgentMesh."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=True)

    event_id: UUID = Field(default_factory=uuid4)
    conversation_id: str
    workflow_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str
    source_agent: str
    routing_mode: RoutingMode = RoutingMode.FANOUT
    target_agent: str | None = None
    payload: JsonPrimitive = Field(default_factory=dict)
    causation_id: UUID | None = None
    causation_chain: list[UUID] = Field(default_factory=list)
    routing_weights: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sequence_number: int | None = None

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation(cls, value: str) -> str:
        return validate_conversation_id(value)

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow(cls, value: str | UUID) -> UUID:
        return validate_workflow_id(value, require_v4=True)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        candidate = str(value).upper()
        if candidate not in VALID_EVENT_TYPES:
            raise InvalidEventTypeError(f"Invalid event_type: {value!r}.")
        return candidate

    @field_validator("source_agent")
    @classmethod
    def validate_source_agent(cls, value: str | None) -> str:
        return validate_agent_name(value, field_name="source_agent")

    @field_validator("target_agent")
    @classmethod
    def validate_target_agent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_agent_name(value, field_name="target_agent")

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: Any) -> Any:
        return validate_json_payload(value)

    @field_validator("routing_weights")
    @classmethod
    def validate_routing_weights(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return None
        if any(weight < 0 for weight in value.values()):
            raise InvalidRoutingError("routing_weights cannot contain negative values.")
        return {str(key): float(weight) for key, weight in value.items()}

    @model_validator(mode="after")
    def validate_routing_and_causation(self) -> Event:
        routing_mode = self.routing_mode
        if isinstance(routing_mode, str):
            routing_mode = RoutingMode(routing_mode)

        if routing_mode == RoutingMode.DIRECTED:
            if not self.target_agent:
                raise InvalidRoutingError("DIRECTED events require target_agent.")
        elif self.target_agent is not None:
            mode_name = routing_mode.value if isinstance(routing_mode, RoutingMode) else str(routing_mode)
            raise InvalidRoutingError(f"{mode_name} events must not include target_agent.")

        if self.routing_weights is not None and any(value < 0 for value in self.routing_weights.values()):
            raise InvalidRoutingError("routing_weights cannot contain negative values.")

        if self.causation_id is not None and self.causation_id == self.event_id:
            raise CausationLoopError("An event cannot be its own cause.")

        normalized_chain = validate_causation_chain(self.causation_chain)
        if self.event_id in normalized_chain:
            raise CausationLoopError("causation_chain cannot contain the current event id.")
        object.__setattr__(self, "causation_chain", normalized_chain)

        if self.causation_id is not None and self.causation_id in normalized_chain:
            raise CausationLoopError("causation_id cannot appear in the causation_chain.")

        return self


class WorkflowState(BaseModel):
    """Projected snapshot derived from the workflow event log."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=True)

    conversation_id: str
    workflow_id: UUID
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: str | None = None
    assigned_agents: list[str] = Field(default_factory=list)
    last_event_id: UUID | None = None
    processed_event_types: list[str] = Field(default_factory=list)
    pending_event_types: list[str] = Field(default_factory=list)

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation(cls, value: str) -> str:
        return validate_conversation_id(value)

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow(cls, value: str | UUID) -> UUID:
        return validate_workflow_id(value, require_v4=True)


class Task(BaseModel):
    """Task payload emitted by the orchestrator or consumed by agents."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=True)

    task_id: UUID = Field(default_factory=uuid4)
    conversation_id: str
    workflow_id: UUID
    task_type: str
    assigned_agent: str | None = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation(cls, value: str) -> str:
        return validate_conversation_id(value)

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow(cls, value: str | UUID) -> UUID:
        return validate_workflow_id(value, require_v4=True)

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, value: str) -> str:
        candidate = str(value).upper()
        if not candidate:
            raise ValidationError("task_type must be a non-empty string.")
        return candidate

    @field_validator("assigned_agent")
    @classmethod
    def validate_assigned_agent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_agent_name(value, field_name="assigned_agent")


class WorkflowContext(BaseModel):
    """Execution context for a workflow managed by the orchestrator."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=True)

    conversation_id: str
    workflow_id: UUID
    goal: str | None = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation(cls, value: str) -> str:
        return validate_conversation_id(value)

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow(cls, value: str | UUID) -> UUID:
        return validate_workflow_id(value, require_v4=True)


class EventFilters(BaseModel):
    """Query filters used to retrieve event rows from the MCP log."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    workflow_id: UUID
    since: datetime | None = None
    event_type: str | None = None
    source_agent: str | None = None
    target_agent: str | None = None
    limit: int = 100

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow(cls, value: str | UUID) -> UUID:
        return validate_workflow_id(value, require_v4=True)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = str(value).upper()
        if candidate not in VALID_EVENT_TYPES:
            raise InvalidEventTypeError(f"Invalid event_type filter: {value!r}.")
        return candidate

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValidationError("limit must be a positive integer.")
        return value


class WorkflowDecision(BaseModel):
    """Decision emitted by the orchestrator to steer workflow progress."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    workflow_id: UUID
    decision_type: str
    next_task: str | None = None
    assigned_agent: str | None = None
    reason: str | None = None

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow(cls, value: str | UUID) -> UUID:
        return validate_workflow_id(value, require_v4=True)

    @field_validator("decision_type")
    @classmethod
    def validate_decision_type(cls, value: str) -> str:
        return _normalise_string(value, field_name="decision_type").upper()

    @field_validator("assigned_agent")
    @classmethod
    def validate_assigned_agent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_agent_name(value, field_name="assigned_agent")


def validate_event(event: Event, *, known_agents: set[str] | None = None) -> Event:
    """Validate a domain event object and ensure it satisfies routing invariants."""

    candidate = event.model_copy(deep=True)
    if known_agents:
        candidate.source_agent = validate_agent_registry(candidate.source_agent, known_agents=known_agents)
        if candidate.target_agent is not None:
            candidate.target_agent = validate_agent_registry(
                candidate.target_agent,
                known_agents=known_agents,
            )
    return candidate


def validate_event_type(value: str) -> str:
    """Compatibility helper for validating raw event-type strings."""

    return Event.model_validate(
        {
            "conversation_id": "conversation",
            "workflow_id": "123e4567-e89b-42d3-a456-426614174000",
            "event_type": value,
            "source_agent": "orchestrator",
        }
    ).event_type


__all__ = [
    "WorkflowStatus",
    "RoutingMode",
    "Event",
    "WorkflowState",
    "Task",
    "WorkflowContext",
    "EventFilters",
    "WorkflowDecision",
    "JsonPrimitive",
    "validate_agent_registry",
    "validate_event",
    "validate_event_type",
    "validate_workflow_id",
    "validate_conversation_id",
]
