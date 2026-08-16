from __future__ import annotations


class AgentMeshError(Exception):
    """Base class for domain-level AgentMesh failures."""


class ValidationError(AgentMeshError):
    """Raised when an input fails domain validation."""


class InvalidEventTypeError(ValidationError):
    """Raised when an event type is not registered."""


class InvalidWorkflowIdError(ValidationError):
    """Raised when a workflow id is missing or malformed."""


class InvalidRoutingError(ValidationError):
    """Raised when routing metadata violates event-model invariants."""


class CausationLoopError(ValidationError):
    """Raised when a causation chain would create a cycle."""


class DuplicateEventError(AgentMeshError):
    """Raised when append is retried with the same idempotency key."""


class WorkflowNotFoundError(AgentMeshError):
    """Raised when a workflow cannot be found in storage."""


class WorkflowConflictError(AgentMeshError):
    """Raised when a workflow identifier is started more than once."""


class ClaimConflictError(AgentMeshError):
    """Raised when an assignment is already leased by another worker."""


class AgentRegistryError(ValidationError):
    """Raised when a source or target agent is not part of the known registry."""


class ModelProviderError(AgentMeshError):
    """Raised when an external model provider cannot produce a usable response."""
