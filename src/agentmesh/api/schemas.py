from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.core.models import HumanDecisionType


class StartWorkflowRequest(BaseModel):
    """Input accepted when starting a master-agent workflow."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    workflow_id: UUID | None = None
    preferred_agent_ids: list[str] = Field(default_factory=list)


class HumanDecisionRequest(BaseModel):
    """Generic plan or task approval response."""

    model_config = ConfigDict(extra="forbid")

    decision: HumanDecisionType
    feedback: str = ""
    actor: str = "human"
    edits: dict[str, Any] = Field(default_factory=dict)


class WorkerClaimRequest(BaseModel):
    """Identity of one worker process requesting an assignment lease."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1)


class WorkerResultRequest(BaseModel):
    """Claim-authenticated terminal result for one assignment."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1)
    claim_token: UUID
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


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
