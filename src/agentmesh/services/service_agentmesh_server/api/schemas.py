from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.core.models import HumanDecisionType, SupervisorActionType


class StartWorkflowRequest(BaseModel):
    """Input accepted when starting a master-agent workflow."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    workflow_id: UUID | None = None
    preferred_agent_ids: list[str] = Field(default_factory=list)
    memory_user_id: str = ""
    memory_opt_in: bool = False
    memory_updates: dict[str, str] = Field(default_factory=dict)
    memory_delete_keys: list[str] = Field(default_factory=list)


class HumanDecisionRequest(BaseModel):
    """Human response to a workflow plan approval request."""

    model_config = ConfigDict(extra="forbid")

    decision: HumanDecisionType
    feedback: str = ""
    actor: str = "human"
    edits: dict[str, Any] = Field(default_factory=dict)


class CheckpointReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)


class WorkflowForkRequest(CheckpointReplayRequest):
    new_workflow_id: UUID
    state_updates: dict[str, Any] = Field(default_factory=dict)


class AgentHeartbeatRequest(BaseModel):
    """Runtime telemetry sent with an agent presence heartbeat."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    runtime_instance_id: str = Field(min_length=1)
    runtime_role: str = "combined"
    runtime_status: str = "READY"
    endpoint: str | None = None
    active_task_count: int = Field(default=0, ge=0)
    started_at: str | None = None
    last_successful_model_call: str | None = None


class WorkerClaimRequest(BaseModel):
    """Identity of one worker process requesting an assignment lease."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1)


class WorkerLeaseRenewRequest(BaseModel):
    """Claim identity used to renew a running assignment lease."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1)
    claim_token: UUID


class WorkerResultRequest(BaseModel):
    """Claim-authenticated terminal result for one assignment."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1)
    claim_token: UUID
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


class SupervisorActionEnqueueRequest(BaseModel):
    """Internal control-plane command destined for the supervisor queue."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    workflow_id: UUID
    action_type: SupervisorActionType
    arguments: dict[str, Any] = Field(default_factory=dict)
    action_event_id: UUID | None = None


class SupervisorActionCompleteRequest(WorkerLeaseRenewRequest):
    result: dict[str, Any] = Field(default_factory=dict)


class SupervisorActionFailureRequest(WorkerLeaseRenewRequest):
    error_code: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    retryable: bool = False
    retry_after_seconds: float = Field(default=0, ge=0, le=3600)


class DirectedAssignmentRequest(BaseModel):
    """One validated task submitted directly to a selected queue worker."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    conversation_id: str | None = None
    thread_id: str | None = None
    user_id: str | None = None


class WorkflowExecutionResponse(BaseModel):
    """Serializable master-agent execution snapshot."""

    workflow_id: str
    conversation_id: str
    status: str
    plan: dict[str, Any] | None = None
    current_task: dict[str, Any] | None = None
    pending_input: dict[str, Any] | None = None
    assigned_agents: list[str] = Field(default_factory=list)
    task_results: list[dict[str, Any]] = Field(default_factory=list)
    rerun_of_workflow_id: str | None = None
    rerun_of_task_id: str | None = None
