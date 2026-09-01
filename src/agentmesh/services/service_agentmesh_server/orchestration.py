from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from agentmesh.core.models import HumanDecisionType


class WorkflowOrchestrator(Protocol):
    """Behavior used by public workflow and worker-result APIs."""

    def graph_mermaid(self) -> str: ...

    def get_workflow(self, workflow_id: UUID) -> dict[str, Any]: ...

    async def astart_workflow(
        self,
        conversation_id: str,
        goal: str,
        *,
        workflow_id: UUID | None = None,
        preferred_agent_ids: list[str] | None = None,
        rerun_of_workflow_id: UUID | None = None,
        rerun_of_task_id: UUID | None = None,
        memory_user_id: str = "",
        memory_opt_in: bool = False,
        memory_updates: dict[str, str] | None = None,
        memory_delete_keys: list[str] | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def asubmit_human_decision(
        self,
        workflow_id: UUID,
        *,
        decision: HumanDecisionType | str,
        feedback: str = "",
        actor: str = "human",
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def asubmit_task_result(
        self,
        workflow_id: UUID,
        *,
        task_id: UUID,
        assignment_event_id: UUID,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def arerun_workflow(self, workflow_id: UUID) -> dict[str, Any]: ...

    async def arerun_task(self, workflow_id: UUID, task_id: UUID) -> dict[str, Any]: ...

    async def arecover_checkpoint(
        self,
        workflow_id: UUID,
        *,
        checkpoint_id: str | None = None,
        new_workflow_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def checkpoint_history(self, workflow_id: UUID) -> list[dict[str, Any]]: ...

    async def replay_checkpoint(
        self, workflow_id: UUID, checkpoint_id: str
    ) -> dict[str, Any]: ...

    async def fork_checkpoint(
        self,
        workflow_id: UUID,
        checkpoint_id: str,
        *,
        new_workflow_id: UUID,
        state_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
