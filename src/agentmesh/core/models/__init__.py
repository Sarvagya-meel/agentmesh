"""Domain models for AgentMesh — re-exported for convenient top-level access.

All concrete definitions live in the sibling modules; this package
re-exports everything so callers can use either:
    from agentmesh.core.models import Event
    from agentmesh.core.models.event import Event
"""

from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.event_types import (
    REGISTERED_EVENT_TYPES,
    VALID_EVENT_TYPES,
    EventType,
)
from agentmesh.core.models.exceptions import (
    AgentMeshError,
    AgentRegistryError,
    CausationLoopError,
    ClaimConflictError,
    DuplicateEventError,
    InvalidEventTypeError,
    InvalidRoutingError,
    InvalidWorkflowIdError,
    ModelProviderError,
    ValidationError,
    WorkflowConflictError,
    WorkflowNotFoundError,
)
from agentmesh.core.models.workflow import (
    ApprovalRequest,
    ApprovalType,
    AssignmentClaim,
    Event,
    EventFilters,
    HumanDecision,
    HumanDecisionType,
    JsonPrimitive,
    PlanTask,
    RoutingMode,
    Task,
    TaskExecutionStatus,
    WorkflowContext,
    WorkflowDecision,
    WorkflowPlan,
    WorkflowState,
    WorkflowStatus,
    validate_agent_registry,
    validate_conversation_id,
    validate_event,
    validate_event_type,
    validate_workflow_id,
)

__all__ = [
    # agent card
    "AgentCard",
    # event types
    "EventType",
    "VALID_EVENT_TYPES",
    "REGISTERED_EVENT_TYPES",
    # exceptions
    "AgentMeshError",
    "AgentRegistryError",
    "CausationLoopError",
    "ClaimConflictError",
    "DuplicateEventError",
    "InvalidEventTypeError",
    "InvalidRoutingError",
    "InvalidWorkflowIdError",
    "ModelProviderError",
    "ValidationError",
    "WorkflowConflictError",
    "WorkflowNotFoundError",
    # workflow models
    "ApprovalRequest",
    "ApprovalType",
    "AssignmentClaim",
    "Event",
    "EventFilters",
    "HumanDecision",
    "HumanDecisionType",
    "JsonPrimitive",
    "PlanTask",
    "RoutingMode",
    "Task",
    "TaskExecutionStatus",
    "WorkflowContext",
    "WorkflowDecision",
    "WorkflowPlan",
    "WorkflowState",
    "WorkflowStatus",
    "validate_agent_registry",
    "validate_conversation_id",
    "validate_event",
    "validate_event_type",
    "validate_workflow_id",
]
