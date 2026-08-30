from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_store
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, interrupt

from agentmesh.agents.agent_langgraph_orchestrator_supervisor.planner import (
    CapabilityWorkflowPlanner,
    WorkflowPlanner,
)
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.execution import ExecutionContext
from agentmesh.core.frameworks.langgraph import load_opt_in_memories
from agentmesh.core.models import (
    ApprovalRequest,
    ApprovalType,
    Event,
    HumanDecision,
    HumanDecisionType,
    PlanTask,
    RoutingMode,
    WorkflowPlan,
    WorkflowStatus,
)
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import (
    AgentRegistryError,
    ValidationError,
    WorkflowConflictError,
)
from agentmesh.core.observability import (
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
    resolve_trace_author,
    trace_author_metadata,
)
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService

ORCHESTRATOR_AGENT_ID = "orchestrator-supervisor-agent"


def merge_task_results(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Commutative, associative, and idempotent reducer for task attempts."""

    by_attempt: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}
    for item in [*left, *right]:
        key = (str(item.get("task_id", "")), int(item.get("attempt_number", 1)))
        canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
        current = by_attempt.get(key)
        if current is None or canonical > current[0]:
            by_attempt[key] = (canonical, item)
    return [
        by_attempt[key][1] for key in sorted(by_attempt, key=lambda value: (value[0], value[1]))
    ]


class MasterWorkflowState(MessagesState, total=False):
    conversation_id: str
    workflow_id: str
    goal: str
    preferred_agent_ids: list[str]
    agent_snapshot: list[dict[str, Any]]
    plan: dict[str, Any]
    plan_version: int
    task_index: int
    current_task: dict[str, Any]
    pending_approval: dict[str, Any]
    decision: str
    feedback: str
    task_results: Annotated[list[dict[str, Any]], merge_task_results]
    task_result_status: str
    agent_result: dict[str, Any]
    assignment_event_id: str
    plan_quality_score: float
    plan_evaluation_attempts: int
    max_plan_evaluation_attempts: int
    plan_evaluation_feedback: str
    memory_user_id: str
    memory_opt_in: bool
    memory_updates: dict[str, str]
    memory_delete_keys: list[str]
    long_term_memories: list[dict[str, Any]]


class MasterOrchestratorAgent(BaseAgent):
    """LangGraph decision engine that coordinates workers exclusively through events."""

    def __init__(
        self,
        *,
        registry_service: RegistryService,
        event_service: EventService,
        state_service: StateService,
        planner: WorkflowPlanner | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        store: BaseStore | None = None,
        agent_stale_seconds: float = 180.0,
        long_term_memory_enabled: bool = False,
        memory_retention_days: int = 30,
        endpoint: str | None = None,
        auto_register: bool = False,
    ) -> None:
        super().__init__(
            ORCHESTRATOR_AGENT_ID,
            auto_register=auto_register,
            endpoint=endpoint or "http://localhost:8000",
            capabilities=[
                "ORCHESTRATE",
                "PLAN",
                "ROUTE",
                "APPROVAL_GATE",
                "WORKFLOW_SUPERVISION",
            ],
            skills=[
                "workflow_planning",
                "agent_routing",
                "human_approval",
                "event_sourcing",
            ],
            description=(
                "Supervisor agent that plans workflows, routes tasks, and gates approvals."
            ),
        )
        self.registry_service = registry_service
        self.event_service = event_service
        self.state_service = state_service
        self.planner = planner or CapabilityWorkflowPlanner()
        self.checkpointer = checkpointer or MemorySaver()
        self.store = store or InMemoryStore()
        self.agent_stale_seconds = agent_stale_seconds
        self.long_term_memory_enabled = long_term_memory_enabled
        self.memory_retention_days = memory_retention_days
        self.graph = self._build_graph()

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        """Start a supervised workflow through the shared agent task contract."""

        nested_payload = task_payload.get("payload", {})
        if not isinstance(nested_payload, dict):
            nested_payload = {}
        goal = str(
            task_payload.get("goal")
            or nested_payload.get("goal")
            or task_payload.get("description")
            or self._last_message(task_payload.get("messages"))
            or ""
        ).strip()
        if not goal:
            raise ValidationError("An orchestrator task requires a goal, description, or message.")

        conversation_id = str(
            task_payload.get("conversation_id")
            or nested_payload.get("conversation_id")
            or f"orchestrator-{uuid4()}"
        ).strip()
        raw_workflow_id = task_payload.get("workflow_id") or nested_payload.get("workflow_id")
        raw_preferred_agents = task_payload.get(
            "preferred_agent_ids",
            nested_payload.get("preferred_agent_ids", []),
        )
        if not isinstance(raw_preferred_agents, list):
            raise ValidationError("preferred_agent_ids must be a list of agent IDs.")

        return self.start_workflow(
            conversation_id,
            goal,
            workflow_id=UUID(str(raw_workflow_id)) if raw_workflow_id else None,
            preferred_agent_ids=[str(agent_id) for agent_id in raw_preferred_agents],
            memory_user_id=str(
                task_payload.get("memory_user_id") or nested_payload.get("memory_user_id") or ""
            ),
            memory_opt_in=bool(
                task_payload.get("memory_opt_in", nested_payload.get("memory_opt_in", False))
            ),
            memory_updates=self._memory_updates(task_payload, nested_payload),
            memory_delete_keys=self._memory_delete_keys(task_payload, nested_payload),
        )

    @staticmethod
    def _last_message(messages: Any) -> str:
        if not isinstance(messages, list) or not messages:
            return ""
        message = messages[-1]
        if isinstance(message, BaseMessage):
            return str(message.content)
        if isinstance(message, dict):
            return str(message.get("content", ""))
        return str(message)

    @staticmethod
    def _memory_updates(
        task_payload: dict[str, Any], nested_payload: dict[str, Any]
    ) -> dict[str, str]:
        values = task_payload.get("memory_updates", nested_payload.get("memory_updates", {}))
        if not isinstance(values, dict):
            raise ValidationError("memory_updates must be an object of string values.")
        return {str(key): str(value) for key, value in values.items()}

    @staticmethod
    def _memory_delete_keys(
        task_payload: dict[str, Any], nested_payload: dict[str, Any]
    ) -> list[str]:
        values = task_payload.get(
            "memory_delete_keys", nested_payload.get("memory_delete_keys", [])
        )
        if not isinstance(values, list):
            raise ValidationError("memory_delete_keys must be a list.")
        return [str(value) for value in values]

    def _build_graph(self) -> Any:
        builder = StateGraph(MasterWorkflowState)
        builder.add_node("load_context", self._load_context)
        builder.add_node("discover_agents", self._discover_agents)
        builder.add_node("create_plan", self._create_plan)
        builder.add_node("evaluate_plan", self._evaluate_plan)
        builder.add_node("request_plan_approval", self._request_plan_approval)
        builder.add_node("review_plan", self._review_plan)
        builder.add_node("prepare_task", self._prepare_task)
        builder.add_node("review_task", self._review_task)
        builder.add_node("dispatch_task", self._dispatch_task)
        builder.add_node("wait_for_task_result", self._wait_for_task_result)
        builder.add_node("request_agent_output_approval", self._request_agent_output_approval)
        builder.add_node("review_agent_output", self._review_agent_output)
        builder.add_node("prepare_agent_resume", self._prepare_agent_resume)
        builder.add_node("advance_task", self._advance_task)
        builder.add_node("complete_workflow", self._complete_workflow)
        builder.add_node("fail_workflow", self._fail_workflow)
        builder.add_node("cancel_workflow", self._cancel_workflow)

        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "discover_agents")
        builder.add_edge("discover_agents", "create_plan")
        builder.add_edge("create_plan", "evaluate_plan")
        builder.add_conditional_edges(
            "evaluate_plan",
            self._plan_evaluation_route,
            {"revise": "create_plan", "complete": "request_plan_approval"},
        )
        builder.add_edge("request_plan_approval", "review_plan")
        builder.add_conditional_edges(
            "review_plan",
            self._decision_route,
            {
                "APPROVE": "prepare_task",
                "REVISE": "create_plan",
                "REJECT": "cancel_workflow",
            },
        )
        # Plan approval currently authorizes every task in that plan. Keep the
        # review_task node below only so older task-approval checkpoints can resume.
        builder.add_edge("prepare_task", "dispatch_task")
        builder.add_conditional_edges(
            "review_task",
            self._decision_route,
            {
                "APPROVE": "dispatch_task",
                "REVISE": "create_plan",
                "REJECT": "cancel_workflow",
            },
        )
        builder.add_edge("dispatch_task", "wait_for_task_result")
        builder.add_conditional_edges(
            "wait_for_task_result",
            self._task_result_route,
            {
                "COMPLETED": "advance_task",
                "FAILED": "fail_workflow",
                "AWAITING_APPROVAL": "request_agent_output_approval",
                "REJECTED": "cancel_workflow",
            },
        )
        builder.add_edge("request_agent_output_approval", "review_agent_output")
        builder.add_edge("review_agent_output", "prepare_agent_resume")
        builder.add_edge("prepare_agent_resume", "dispatch_task")
        builder.add_conditional_edges(
            "advance_task",
            self._advance_route,
            {"NEXT": "prepare_task", "COMPLETE": "complete_workflow"},
        )
        builder.add_edge("complete_workflow", END)
        builder.add_edge("fail_workflow", END)
        builder.add_edge("cancel_workflow", END)
        return builder.compile(checkpointer=self.checkpointer, store=self.store)

    def start_workflow(
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
    ) -> dict[str, Any]:
        """Start planning and run until the plan approval checkpoint."""

        resolved_workflow_id = workflow_id or uuid4()
        if self.event_service.replay(resolved_workflow_id):
            raise WorkflowConflictError(f"Workflow {resolved_workflow_id} already exists.")
        self._emit_raw(
            conversation_id=conversation_id,
            workflow_id=resolved_workflow_id,
            event_type="WORKFLOW_STARTED",
            payload={
                "goal": goal,
                "rerun_of_workflow_id": (
                    str(rerun_of_workflow_id) if rerun_of_workflow_id else None
                ),
                "rerun_of_task_id": str(rerun_of_task_id) if rerun_of_task_id else None,
            },
        )
        try:
            result = self.graph.invoke(
                {
                    "messages": [HumanMessage(content=goal)],
                    "conversation_id": conversation_id,
                    "workflow_id": str(resolved_workflow_id),
                    "goal": goal,
                    "preferred_agent_ids": preferred_agent_ids or [],
                    "plan_version": 0,
                    "task_index": 0,
                    "task_results": [],
                    "feedback": "",
                    "plan_evaluation_attempts": 0,
                    "max_plan_evaluation_attempts": 3,
                    "memory_user_id": memory_user_id,
                    "memory_opt_in": memory_opt_in,
                    "memory_updates": memory_updates or {},
                    "memory_delete_keys": memory_delete_keys or [],
                },
                config=self._config(
                    resolved_workflow_id,
                    {"run_id": str(uuid4()), "operation": "start_workflow"},
                ),
            )
        except Exception as exc:
            self._emit_raw(
                conversation_id=conversation_id,
                workflow_id=resolved_workflow_id,
                event_type="WORKFLOW_FAILED",
                payload={"stage": "planning", "error_type": type(exc).__name__},
            )
            raise
        return self._format_result(resolved_workflow_id, result)

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
    ) -> dict[str, Any]:
        resolved_workflow_id = workflow_id or uuid4()
        raw_metadata: dict[str, Any] = {
            "agent_id": self.agent_name,
            "execution_mode": "workflow",
            "operation": "start_workflow",
            "workflow_id": resolved_workflow_id,
            "conversation_id": conversation_id,
            "preferred_agent_ids": ",".join(preferred_agent_ids or []),
            "rerun_of_workflow_id": rerun_of_workflow_id,
            "rerun_of_task_id": rerun_of_task_id,
            "memory_opt_in": memory_opt_in,
        }
        raw_metadata.update(trace_metadata or {})
        author = resolve_trace_author(
            raw_metadata.get("trigger_source") or self.agent_name,
            agent_card=None if raw_metadata.get("trigger_source") else self.agent_card(),
        )
        metadata = agentmesh_metadata(**raw_metadata, **trace_author_metadata(author))
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                resolved_workflow_id,
                goal,
                author.author_name,
            ),
            inputs={"goal": goal, "preferred_agent_ids": preferred_agent_ids or []},
            metadata=metadata,
            tags=["workflow", "orchestrator", self.agent_name],
        ) as run:
            if self.event_service.replay(resolved_workflow_id):
                raise WorkflowConflictError(f"Workflow {resolved_workflow_id} already exists.")
            self._emit_raw(
                conversation_id=conversation_id,
                workflow_id=resolved_workflow_id,
                event_type="WORKFLOW_STARTED",
                payload={
                    "goal": goal,
                    "rerun_of_workflow_id": (
                        str(rerun_of_workflow_id) if rerun_of_workflow_id else None
                    ),
                    "rerun_of_task_id": str(rerun_of_task_id) if rerun_of_task_id else None,
                },
            )
            try:
                result = await self.graph.ainvoke(
                    {
                        "messages": [HumanMessage(content=goal)],
                        "conversation_id": conversation_id,
                        "workflow_id": str(resolved_workflow_id),
                        "goal": goal,
                        "preferred_agent_ids": preferred_agent_ids or [],
                        "plan_version": 0,
                        "task_index": 0,
                        "task_results": [],
                        "feedback": "",
                        "plan_evaluation_attempts": 0,
                        "max_plan_evaluation_attempts": 3,
                        "memory_user_id": memory_user_id,
                        "memory_opt_in": memory_opt_in,
                        "memory_updates": memory_updates or {},
                        "memory_delete_keys": memory_delete_keys or [],
                    },
                    config=self._config(
                        resolved_workflow_id,
                        {
                            "run_id": str(uuid4()),
                            "operation": "start_workflow",
                            "execution_mode": "workflow",
                            **(trace_metadata or {}),
                        },
                    ),
                )
            except Exception as exc:
                self._emit_raw(
                    conversation_id=conversation_id,
                    workflow_id=resolved_workflow_id,
                    event_type="WORKFLOW_FAILED",
                    payload={"stage": "planning", "error_type": type(exc).__name__},
                )
                raise
            response = self._format_result(resolved_workflow_id, dict(result))
            if run is not None:
                run.end(outputs={"workflow_status": response["status"]})
            return response

    async def arun_task(
        self,
        task_payload: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        nested_payload = task_payload.get("payload", {})
        if not isinstance(nested_payload, dict):
            nested_payload = {}
        goal = str(
            task_payload.get("goal")
            or nested_payload.get("goal")
            or task_payload.get("description")
            or self._last_message(task_payload.get("messages"))
            or ""
        ).strip()
        if not goal:
            raise ValidationError("An orchestrator task requires a goal, description, or message.")
        raw_preferred_agents = task_payload.get(
            "preferred_agent_ids", nested_payload.get("preferred_agent_ids", [])
        )
        if not isinstance(raw_preferred_agents, list):
            raise ValidationError("preferred_agent_ids must be a list of agent IDs.")
        raw_workflow_id = task_payload.get("workflow_id") or nested_payload.get("workflow_id")
        return await self.astart_workflow(
            str(
                task_payload.get("conversation_id")
                or nested_payload.get("conversation_id")
                or f"orchestrator-{uuid4()}"
            ),
            goal,
            workflow_id=UUID(str(raw_workflow_id)) if raw_workflow_id else None,
            preferred_agent_ids=[str(item) for item in raw_preferred_agents],
            memory_user_id=str(
                task_payload.get("memory_user_id") or nested_payload.get("memory_user_id") or ""
            ),
            memory_opt_in=bool(
                task_payload.get("memory_opt_in", nested_payload.get("memory_opt_in", False))
            ),
            memory_updates=self._memory_updates(task_payload, nested_payload),
            memory_delete_keys=self._memory_delete_keys(task_payload, nested_payload),
            trace_metadata=self._trace_metadata(context, task_payload),
        )

    def _load_context(self, state: MasterWorkflowState) -> dict[str, Any]:
        return {
            "long_term_memories": load_opt_in_memories(
                get_store(),
                agent_id=self.agent_name,
                enabled=self.long_term_memory_enabled,
                user_id=state.get("memory_user_id", ""),
                opt_in=state.get("memory_opt_in", False),
                updates=state.get("memory_updates", {}),
                delete_keys=state.get("memory_delete_keys", []),
                retention_days=self.memory_retention_days,
            )
        }

    def submit_human_decision(
        self,
        workflow_id: UUID,
        *,
        decision: HumanDecisionType | str,
        feedback: str = "",
        actor: str = "human",
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume a plan or task approval checkpoint with an auditable decision."""

        current = self.state_service.get_current(workflow_id)
        if current.status not in {
            WorkflowStatus.AWAITING_PLAN_APPROVAL,
            WorkflowStatus.AWAITING_TASK_APPROVAL,
            WorkflowStatus.AWAITING_AGENT_APPROVAL,
        }:
            raise ValidationError(f"Workflow {workflow_id} is not waiting for human approval.")
        pending = ApprovalRequest.model_validate(current.metadata["pending_approval"])
        human_decision = HumanDecision(
            approval_id=pending.approval_id,
            workflow_id=workflow_id,
            decision=decision,
            feedback=feedback,
            actor=actor,
            edits=edits or {},
        )
        result = self.graph.invoke(
            Command(resume=human_decision.model_dump(mode="json")),
            config=self._config(
                workflow_id,
                {"run_id": str(uuid4()), "operation": "submit_approval"},
            ),
        )
        return self._format_result(workflow_id, result)

    async def asubmit_human_decision(
        self,
        workflow_id: UUID,
        *,
        decision: HumanDecisionType | str,
        feedback: str = "",
        actor: str = "human",
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume a plan or task approval through the native async graph API."""

        current = self.state_service.get_current(workflow_id)
        if current.status not in {
            WorkflowStatus.AWAITING_PLAN_APPROVAL,
            WorkflowStatus.AWAITING_TASK_APPROVAL,
            WorkflowStatus.AWAITING_AGENT_APPROVAL,
        }:
            raise ValidationError(f"Workflow {workflow_id} is not waiting for human approval.")
        pending = ApprovalRequest.model_validate(current.metadata["pending_approval"])
        author = resolve_trace_author(actor, author_type="human")
        metadata = agentmesh_metadata(
            agent_id=self.agent_name,
            execution_mode="workflow",
            operation="submit_approval",
            workflow_id=workflow_id,
            conversation_id=current.conversation_id,
            approval_id=pending.approval_id,
            approval_type=pending.approval_type,
            subject_id=pending.subject_id,
            decision=decision,
            actor=actor,
            **trace_author_metadata(author),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                workflow_id,
                f"approval resume {pending.approval_type}",
                author.author_name,
            ),
            inputs={"decision": str(decision), "feedback_present": bool(feedback)},
            metadata=metadata,
            tags=["workflow", "approval", "interrupt", self.agent_name],
        ) as run:
            human_decision = HumanDecision(
                approval_id=pending.approval_id,
                workflow_id=workflow_id,
                decision=decision,
                feedback=feedback,
                actor=actor,
                edits=edits or {},
            )
            result = await self.graph.ainvoke(
                Command(resume=human_decision.model_dump(mode="json")),
                config=self._config(
                    workflow_id,
                    {
                        "run_id": str(uuid4()),
                        "operation": "submit_approval",
                        "execution_mode": "workflow",
                        "approval_id": str(pending.approval_id),
                        "approval_type": str(pending.approval_type),
                    },
                ),
            )
            response = self._format_result(workflow_id, dict(result))
            if run is not None:
                run.end(outputs={"workflow_status": response["status"]})
            return response

    def submit_task_result(
        self,
        workflow_id: UUID,
        *,
        task_id: UUID,
        assignment_event_id: UUID | None = None,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume a waiting workflow when its assigned worker emits a result."""

        current = self.state_service.get_current(workflow_id)
        if current.status != WorkflowStatus.WAITING_FOR_AGENT:
            raise ValidationError(f"Workflow {workflow_id} is not waiting for an agent result.")
        normalized_status = status.strip().upper()
        if normalized_status not in {
            "COMPLETED",
            "FAILED",
            "AWAITING_APPROVAL",
            "REJECTED",
        }:
            raise ValidationError(
                "Task result status must be COMPLETED, FAILED, AWAITING_APPROVAL, or REJECTED."
            )
        payload = {
            "task_id": str(task_id),
            "assignment_event_id": str(
                assignment_event_id or current.metadata.get("assignment_event_id", "")
            ),
            "status": normalized_status,
            "result": result or {},
        }
        graph_result = self.graph.invoke(
            Command(resume=payload),
            config=self._config(workflow_id),
        )
        return self._format_result(workflow_id, graph_result)

    async def asubmit_task_result(
        self,
        workflow_id: UUID,
        *,
        task_id: UUID,
        assignment_event_id: UUID | None = None,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume an assigned task through the native async graph API."""

        current = self.state_service.get_current(workflow_id)
        normalized_status = status.strip().upper()
        resolved_assignment_id = assignment_event_id or current.metadata.get(
            "assignment_event_id", ""
        )
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        metadata = agentmesh_metadata(
            agent_id=self.agent_name,
            agent_name=author.author_name,
            execution_mode="workflow",
            operation="submit_task_result",
            workflow_id=workflow_id,
            conversation_id=current.conversation_id,
            task_id=task_id,
            assignment_event_id=resolved_assignment_id,
            assignment_id=resolved_assignment_id,
            task_result_status=normalized_status,
            **trace_author_metadata(author),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                workflow_id,
                f"task result {normalized_status}",
                author.author_name,
            ),
            inputs={"status": normalized_status, "result_keys": sorted(result or {})},
            metadata=metadata,
            tags=["workflow", "task-result", "interrupt", self.agent_name],
        ) as run:
            if current.status != WorkflowStatus.WAITING_FOR_AGENT:
                raise ValidationError(f"Workflow {workflow_id} is not waiting for an agent result.")
            if normalized_status not in {
                "COMPLETED",
                "FAILED",
                "AWAITING_APPROVAL",
                "REJECTED",
            }:
                raise ValidationError(
                    "Task result status must be COMPLETED, FAILED, AWAITING_APPROVAL, or REJECTED."
                )
            payload = {
                "task_id": str(task_id),
                "assignment_event_id": str(resolved_assignment_id),
                "status": normalized_status,
                "result": result or {},
            }
            graph_result = await self.graph.ainvoke(
                Command(resume=payload),
                config=self._config(
                    workflow_id,
                    {
                        "run_id": str(uuid4()),
                        "operation": "submit_task_result",
                        "execution_mode": "workflow",
                        "task_id": str(task_id),
                        "assignment_event_id": str(resolved_assignment_id),
                        "assignment_id": str(resolved_assignment_id),
                    },
                ),
            )
            response = self._format_result(workflow_id, dict(graph_result))
            if run is not None:
                run.end(outputs={"workflow_status": response["status"]})
            return response

    def get_workflow(self, workflow_id: UUID) -> dict[str, Any]:
        """Return event-projected workflow status without mutating execution."""

        return self._format_result(workflow_id, None)

    def rerun_workflow(self, workflow_id: UUID) -> dict[str, Any]:
        current = self.state_service.get_current(workflow_id)
        goal = str(current.metadata.get("goal", "")).strip()
        if not goal:
            raise ValidationError("The original workflow has no goal to rerun.")
        plan = current.metadata.get("plan", {})
        tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
        preferred_agents = list(
            dict.fromkeys(
                str(task.get("agent_id"))
                for task in tasks
                if isinstance(task, dict) and task.get("agent_id")
            )
        )
        new_workflow_id = uuid4()
        self._emit_raw(
            conversation_id=current.conversation_id,
            workflow_id=workflow_id,
            event_type="WORKFLOW_RERUN_REQUESTED",
            payload={"new_workflow_id": str(new_workflow_id)},
        )
        return self.start_workflow(
            current.conversation_id,
            goal,
            workflow_id=new_workflow_id,
            preferred_agent_ids=preferred_agents,
            rerun_of_workflow_id=workflow_id,
        )

    def rerun_task(self, workflow_id: UUID, task_id: UUID) -> dict[str, Any]:
        current = self.state_service.get_current(workflow_id)
        plan = current.metadata.get("plan", {})
        tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
        task = next(
            (
                PlanTask.model_validate(item)
                for item in tasks
                if isinstance(item, dict) and str(item.get("task_id")) == str(task_id)
            ),
            None,
        )
        if task is None:
            raise ValidationError(f"Task {task_id} does not belong to workflow {workflow_id}.")
        new_workflow_id = uuid4()
        self._emit_raw(
            conversation_id=current.conversation_id,
            workflow_id=workflow_id,
            event_type="TASK_RERUN_REQUESTED",
            payload={"task_id": str(task_id), "new_workflow_id": str(new_workflow_id)},
        )
        return self.start_workflow(
            current.conversation_id,
            task.description,
            workflow_id=new_workflow_id,
            preferred_agent_ids=[task.agent_id],
            rerun_of_workflow_id=workflow_id,
            rerun_of_task_id=task_id,
        )

    async def arerun_workflow(self, workflow_id: UUID) -> dict[str, Any]:
        current = self.state_service.get_current(workflow_id)
        goal = str(current.metadata.get("goal", "")).strip()
        if not goal:
            raise ValidationError("The original workflow has no goal to rerun.")
        plan = current.metadata.get("plan", {})
        tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
        preferred_agents = list(
            dict.fromkeys(
                str(task.get("agent_id"))
                for task in tasks
                if isinstance(task, dict) and task.get("agent_id")
            )
        )
        new_workflow_id = uuid4()
        self._emit_raw(
            conversation_id=current.conversation_id,
            workflow_id=workflow_id,
            event_type="WORKFLOW_RERUN_REQUESTED",
            payload={"new_workflow_id": str(new_workflow_id)},
        )
        return await self.astart_workflow(
            current.conversation_id,
            goal,
            workflow_id=new_workflow_id,
            preferred_agent_ids=preferred_agents,
            rerun_of_workflow_id=workflow_id,
        )

    async def arerun_task(self, workflow_id: UUID, task_id: UUID) -> dict[str, Any]:
        current = self.state_service.get_current(workflow_id)
        plan = current.metadata.get("plan", {})
        tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
        task = next(
            (
                PlanTask.model_validate(item)
                for item in tasks
                if isinstance(item, dict) and str(item.get("task_id")) == str(task_id)
            ),
            None,
        )
        if task is None:
            raise ValidationError(f"Task {task_id} does not belong to workflow {workflow_id}.")
        new_workflow_id = uuid4()
        self._emit_raw(
            conversation_id=current.conversation_id,
            workflow_id=workflow_id,
            event_type="TASK_RERUN_REQUESTED",
            payload={"task_id": str(task_id), "new_workflow_id": str(new_workflow_id)},
        )
        return await self.astart_workflow(
            current.conversation_id,
            task.description,
            workflow_id=new_workflow_id,
            preferred_agent_ids=[task.agent_id],
            rerun_of_workflow_id=workflow_id,
            rerun_of_task_id=task_id,
        )

    def _discover_agents(self, state: MasterWorkflowState) -> dict[str, Any]:
        cards = self.registry_service.list_agents()
        online_cards = [
            card
            for card in cards
            if card.status == "online"
            and self._is_worker_agent(card)
            and bool(card.metadata.get("assignment_ready", True))
            and self._is_recent_agent(card)
        ]
        if not online_cards:
            raise AgentRegistryError("No online agents are registered.")
        snapshot = [card.model_dump(mode="json") for card in online_cards]
        self._emit(state, "AGENT_SNAPSHOT_CAPTURED", {"agents": snapshot})
        return {"agent_snapshot": snapshot}

    def _create_plan(self, state: MasterWorkflowState) -> dict[str, Any]:
        previous_plan = WorkflowPlan.model_validate(state["plan"]) if state.get("plan") else None
        cards = [AgentCard.model_validate(item) for item in state["agent_snapshot"]]
        plan = self.planner.create_plan(
            workflow_id=UUID(state["workflow_id"]),
            goal=state["goal"],
            agents=cards,
            preferred_agent_ids=state.get("preferred_agent_ids", []),
            feedback=state.get("feedback", ""),
            previous_plan=previous_plan,
            long_term_memories=state.get("long_term_memories", []),
        )
        plan_payload = plan.model_dump(mode="json")
        self._validate_plan(plan, cards)
        self._emit(state, "PLAN_CREATED", {"plan": plan_payload})
        return {
            "plan": plan_payload,
            "plan_version": plan.version,
            "task_index": 0,
            "feedback": "",
        }

    def _request_plan_approval(self, state: MasterWorkflowState) -> dict[str, Any]:
        plan = WorkflowPlan.model_validate(state["plan"])
        approval = ApprovalRequest(
            workflow_id=plan.workflow_id,
            approval_type=ApprovalType.PLAN,
            subject_id=plan.plan_id,
            prompt=f"Approve workflow plan version {plan.version} before tasks are prepared?",
            context={"plan": plan.model_dump(mode="json")},
        )
        payload = approval.model_dump(mode="json")
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                state["workflow_id"],
                "plan approval requested",
                author.author_name,
            ),
            inputs={"approval": payload},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                workflow_id=state["workflow_id"],
                conversation_id=state["conversation_id"],
                plan_id=plan.plan_id,
                plan_version=plan.version,
                approval_id=approval.approval_id,
                approval_type=approval.approval_type,
                execution_mode="workflow",
                interrupt_type="human_approval",
                **trace_author_metadata(author),
            ),
            tags=["workflow", "approval", "interrupt", self.agent_name],
        ):
            self._emit(state, "PLAN_APPROVAL_REQUESTED", {"approval": payload})
        return {"pending_approval": payload}

    @staticmethod
    def _evaluate_plan(state: MasterWorkflowState) -> dict[str, Any]:
        plan = WorkflowPlan.model_validate(state["plan"])
        issues = []
        if len(plan.rationale.split()) < 4:
            issues.append("Provide a clearer planning rationale.")
        if any(len(task.description.split()) < 5 for task in plan.tasks):
            issues.append("Make each task description concrete and actionable.")
        if any(len(task.expected_output.split()) < 2 for task in plan.tasks):
            issues.append("Define a useful expected output for every task.")
        feedback = " ".join(issues)
        return {
            "plan_quality_score": 1.0 if not issues else 0.5,
            "plan_evaluation_attempts": int(state.get("plan_evaluation_attempts", 0)) + 1,
            "plan_evaluation_feedback": feedback,
            "feedback": feedback,
        }

    @staticmethod
    def _plan_evaluation_route(state: MasterWorkflowState) -> str:
        if state.get("plan_quality_score", 0.0) < 0.8 and state.get(
            "plan_evaluation_attempts", 0
        ) < state.get("max_plan_evaluation_attempts", 3):
            return "revise"
        return "complete"

    def _review_plan(self, state: MasterWorkflowState) -> dict[str, Any]:
        decision = self._interrupt_for_decision(state)
        event_type = {
            "APPROVE": "PLAN_APPROVED",
            "REVISE": "PLAN_REVISION_REQUESTED",
            "REJECT": "PLAN_REJECTED",
        }[decision.decision]
        self._emit(
            state,
            event_type,
            {"decision": decision.model_dump(mode="json"), "feedback": decision.feedback},
        )
        return {
            "decision": decision.decision,
            "feedback": decision.feedback,
            "pending_approval": {},
            "plan_evaluation_attempts": (
                0 if decision.decision == "REVISE" else state.get("plan_evaluation_attempts", 0)
            ),
        }

    def _prepare_task(self, state: MasterWorkflowState) -> dict[str, Any]:
        plan = WorkflowPlan.model_validate(state["plan"])
        task = plan.tasks[state.get("task_index", 0)]
        task_payload = task.model_dump(mode="json")
        self._emit(state, "TASK_PROPOSED", {"task": task_payload, "plan_id": str(plan.plan_id)})
        return {"current_task": task_payload, "pending_approval": {}}

    def _review_task(self, state: MasterWorkflowState) -> dict[str, Any]:
        decision = self._interrupt_for_decision(state)
        event_type = {
            "APPROVE": "TASK_APPROVED",
            "REVISE": "TASK_REVISION_REQUESTED",
            "REJECT": "TASK_REJECTED",
        }[decision.decision]
        self._emit(
            state,
            event_type,
            {"decision": decision.model_dump(mode="json"), "feedback": decision.feedback},
        )
        return {
            "decision": decision.decision,
            "feedback": decision.feedback,
            "pending_approval": {},
        }

    def _dispatch_task(self, state: MasterWorkflowState) -> dict[str, Any]:
        task = PlanTask.model_validate(state["current_task"])
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        target_author = resolve_trace_author(
            task.agent_id,
            agent_card=self.registry_service.get_agent(task.agent_id),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                state["workflow_id"],
                f"assignment {task.name}",
                author.author_name,
            ),
            inputs={"task": task.model_dump(mode="json")},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                target_agent=task.agent_id,
                target_agent_name=target_author.author_name,
                workflow_id=state["workflow_id"],
                conversation_id=state["conversation_id"],
                task_id=task.task_id,
                task_name=task.name,
                required_capability=task.required_capability,
                execution_mode="workflow",
                **trace_author_metadata(author),
            ),
            tags=["workflow", "dispatch", task.agent_id],
        ) as run:
            assignment = self._emit(
                state,
                "TASK_ASSIGNED",
                {"task": task.model_dump(mode="json"), "task_type": task.required_capability},
                routing_mode=RoutingMode.DIRECTED,
                target_agent=task.agent_id,
            )
            if run is not None:
                run.end(outputs={"assignment_event_id": str(assignment.event_id)})
        return {
            "current_task": task.model_dump(mode="json"),
            "assignment_event_id": str(assignment.event_id),
        }

    def _wait_for_task_result(self, state: MasterWorkflowState) -> dict[str, Any]:
        task = PlanTask.model_validate(state["current_task"])
        response = interrupt(
            {
                "type": "agent_result",
                "workflow_id": state["workflow_id"],
                "task": task.model_dump(mode="json"),
            }
        )
        if not isinstance(response, dict):
            raise ValidationError("Agent result must be a structured object.")
        if str(response.get("task_id")) != str(task.task_id):
            raise ValidationError("Agent result task_id does not match the assigned task.")
        if str(response.get("assignment_event_id")) != state.get("assignment_event_id"):
            raise ValidationError("Agent result does not match the active assignment event.")
        status = str(response.get("status", "")).upper()
        if status not in {"COMPLETED", "FAILED", "AWAITING_APPROVAL", "REJECTED"}:
            raise ValidationError("Agent returned an unsupported task result status.")
        event_payload = {
            "task_id": str(task.task_id),
            "assignment_event_id": state["assignment_event_id"],
            "result": response.get("result", {}),
        }
        if status == "AWAITING_APPROVAL":
            result = response.get("result", {})
            if not isinstance(result, dict) or not result.get("thread_id"):
                raise ValidationError("An agent approval result must include a durable thread_id.")
            self._emit(
                state,
                "AGENT_OUTPUT_PROPOSED",
                event_payload,
                source_agent=task.agent_id,
                causation_id=UUID(state["assignment_event_id"]),
            )
            return {"task_result_status": status, "agent_result": result}
        if status == "REJECTED":
            return {"task_result_status": status, "agent_result": response.get("result", {})}

        event_type = "TASK_COMPLETED" if status == "COMPLETED" else "TASK_FAILED"
        self._emit(
            state,
            event_type,
            event_payload,
            source_agent=task.agent_id,
            causation_id=UUID(state["assignment_event_id"]),
        )
        event_payload["attempt_number"] = int(
            response.get("result", {}).get("attempt_number", 1)
            if isinstance(response.get("result"), dict)
            else 1
        )
        return {"task_result_status": status, "task_results": [event_payload]}

    def _request_agent_output_approval(self, state: MasterWorkflowState) -> dict[str, Any]:
        task = PlanTask.model_validate(state["current_task"])
        agent_result = state.get("agent_result", {})
        approval = ApprovalRequest(
            workflow_id=UUID(state["workflow_id"]),
            approval_type=ApprovalType.AGENT_OUTPUT,
            subject_id=task.task_id,
            prompt=str(
                agent_result.get(
                    "prompt",
                    f"Review output from {task.agent_id} before accepting the task.",
                )
            ),
            context={
                "agent_id": task.agent_id,
                "task": task.model_dump(mode="json"),
                "thread_id": agent_result["thread_id"],
                "draft_reply": agent_result.get("draft_reply", ""),
                "agent_output": agent_result,
            },
        )
        payload = approval.model_dump(mode="json")
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        target_author = resolve_trace_author(
            task.agent_id,
            agent_card=self.registry_service.get_agent(task.agent_id),
        )
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                state["workflow_id"],
                "agent-output approval requested",
                author.author_name,
            ),
            inputs={"approval": payload},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                target_agent=task.agent_id,
                target_agent_name=target_author.author_name,
                workflow_id=state["workflow_id"],
                conversation_id=state["conversation_id"],
                task_id=task.task_id,
                approval_id=approval.approval_id,
                approval_type=approval.approval_type,
                thread_id=agent_result.get("thread_id"),
                execution_mode="workflow",
                interrupt_type="human_approval",
                **trace_author_metadata(author),
            ),
            tags=["workflow", "approval", "interrupt", task.agent_id],
        ):
            self._emit(state, "AGENT_APPROVAL_REQUESTED", {"approval": payload})
        return {"pending_approval": payload}

    def _review_agent_output(self, state: MasterWorkflowState) -> dict[str, Any]:
        decision = self._interrupt_for_decision(state)
        event_type = {
            "APPROVE": "AGENT_OUTPUT_APPROVED",
            "REVISE": "AGENT_OUTPUT_REVISION_REQUESTED",
            "REJECT": "AGENT_OUTPUT_REJECTED",
        }[decision.decision]
        self._emit(
            state,
            event_type,
            {"decision": decision.model_dump(mode="json"), "feedback": decision.feedback},
        )
        return {
            "decision": decision.decision,
            "feedback": decision.feedback,
            "pending_approval": {},
        }

    def _prepare_agent_resume(self, state: MasterWorkflowState) -> dict[str, Any]:
        task = PlanTask.model_validate(state["current_task"])
        agent_result = state.get("agent_result", {})
        payload = dict(task.payload)
        payload.update(
            {
                "resume_thread_id": agent_result["thread_id"],
                "approval_decision": state["decision"].lower(),
                "approval_feedback": state.get("feedback", ""),
            }
        )
        resumed_task = task.model_copy(update={"payload": payload})
        return {
            "current_task": resumed_task.model_dump(mode="json"),
            "agent_result": {},
        }

    def _advance_task(self, state: MasterWorkflowState) -> dict[str, Any]:
        return {"task_index": state.get("task_index", 0) + 1}

    def _complete_workflow(self, state: MasterWorkflowState) -> dict[str, Any]:
        self._emit(state, "WORKFLOW_COMPLETED", {"task_results": state.get("task_results", [])})
        return {}

    def _fail_workflow(self, state: MasterWorkflowState) -> dict[str, Any]:
        self._emit(
            state,
            "WORKFLOW_FAILED",
            {"task": state.get("current_task", {}), "task_results": state.get("task_results", [])},
        )
        return {}

    def _cancel_workflow(self, state: MasterWorkflowState) -> dict[str, Any]:
        self._emit(state, "WORKFLOW_CANCELLED", {"feedback": state.get("feedback", "")})
        return {}

    def _interrupt_for_decision(self, state: MasterWorkflowState) -> HumanDecision:
        approval = ApprovalRequest.model_validate(state["pending_approval"])
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        interrupt_payload = {
            "type": "human_approval",
            "approval": approval.model_dump(mode="json"),
            "prompt": approval.prompt,
            "options": [
                {"label": option.title(), "value": str(option)} for option in approval.options
            ],
            **approval.context,
        }
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                state["workflow_id"],
                f"human approval interrupt {approval.approval_type}",
                author.author_name,
            ),
            inputs={
                "approval_id": str(approval.approval_id),
                "approval_type": str(approval.approval_type),
                "option_count": len(approval.options),
            },
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                workflow_id=state["workflow_id"],
                conversation_id=state["conversation_id"],
                approval_id=approval.approval_id,
                approval_type=approval.approval_type,
                subject_id=approval.subject_id,
                execution_mode="workflow",
                interrupt_type="human_approval",
                **trace_author_metadata(author),
            ),
            tags=["workflow", "approval", "interrupt", self.agent_name],
        ):
            response = interrupt(interrupt_payload)
        decision = HumanDecision.model_validate(response)
        if decision.approval_id != approval.approval_id:
            raise ValidationError("Human decision does not match the pending approval request.")
        return decision

    @staticmethod
    def _validate_plan(plan: WorkflowPlan, cards: list[AgentCard]) -> None:
        known_agents = {card.agent_id: card for card in cards if card.status == "online"}
        seen_tasks: set[UUID] = set()
        for position, task in enumerate(plan.tasks):
            if task.position != position:
                raise ValidationError("Plan task positions must be contiguous and ordered.")
            if task.agent_id not in known_agents:
                raise AgentRegistryError(
                    f"Plan selected unknown or offline agent {task.agent_id!r}."
                )
            card = known_agents[task.agent_id]
            advertised = {capability.upper() for capability in card.capabilities}
            required = task.required_capability.upper()
            if required not in advertised and not (required == "GENERAL" and not advertised):
                raise AgentRegistryError(
                    f"Agent {card.agent_id!r} does not advertise capability {required!r}."
                )
            if any(dependency not in seen_tasks for dependency in task.dependencies):
                raise ValidationError("Plan tasks may depend only on earlier tasks.")
            seen_tasks.add(task.task_id)

    @staticmethod
    def _decision_route(state: MasterWorkflowState) -> str:
        return state["decision"]

    @staticmethod
    def _task_result_route(state: MasterWorkflowState) -> str:
        return state["task_result_status"]

    @staticmethod
    def _is_worker_agent(card: AgentCard) -> bool:
        return (
            card.agent_id != ORCHESTRATOR_AGENT_ID
            and str(card.metadata.get("resource_type", "")).lower() != "orchestrator"
        )

    def _is_recent_agent(self, card: AgentCard) -> bool:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.agent_stale_seconds)
        seen_at = card.last_seen
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=UTC)
        return seen_at >= cutoff

    @staticmethod
    def _advance_route(state: MasterWorkflowState) -> str:
        plan = WorkflowPlan.model_validate(state["plan"])
        return "COMPLETE" if state["task_index"] >= len(plan.tasks) else "NEXT"

    def _emit(
        self,
        state: MasterWorkflowState,
        event_type: str,
        payload: dict[str, Any],
        *,
        source_agent: str = ORCHESTRATOR_AGENT_ID,
        routing_mode: RoutingMode = RoutingMode.FANOUT,
        target_agent: str | None = None,
        causation_id: UUID | None = None,
    ) -> Event:
        snapshot = state.get("agent_snapshot", [])
        known_agents = {str(card["agent_id"]) for card in snapshot}
        return self._emit_raw(
            conversation_id=state["conversation_id"],
            workflow_id=UUID(state["workflow_id"]),
            event_type=event_type,
            payload=payload,
            source_agent=source_agent,
            routing_mode=routing_mode,
            target_agent=target_agent,
            causation_id=causation_id,
            known_agents=known_agents or None,
        )

    def _emit_raw(
        self,
        *,
        conversation_id: str,
        workflow_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        source_agent: str = ORCHESTRATOR_AGENT_ID,
        routing_mode: RoutingMode = RoutingMode.FANOUT,
        target_agent: str | None = None,
        causation_id: UUID | None = None,
        known_agents: set[str] | None = None,
    ) -> Event:
        return self.event_service.append(
            Event(
                conversation_id=conversation_id,
                workflow_id=workflow_id,
                event_type=event_type,
                source_agent=source_agent,
                routing_mode=routing_mode,
                target_agent=target_agent,
                payload=payload,
                causation_id=causation_id,
            ),
            known_agents=known_agents,
        )

    @staticmethod
    def _config(
        workflow_id: UUID,
        metadata: dict[str, Any] | None = None,
    ) -> RunnableConfig:
        author = resolve_trace_author(ORCHESTRATOR_AGENT_ID)
        return {
            "configurable": {"thread_id": str(workflow_id)},
            "run_name": agentmesh_run_name(
                "WorkFlow",
                workflow_id,
                str(metadata.get("operation", "graph") if metadata else "graph"),
                author.author_name,
            ),
            "tags": ["agentmesh", "workflow", ORCHESTRATOR_AGENT_ID],
            "metadata": {
                "agent_id": ORCHESTRATOR_AGENT_ID,
                "agent_name": author.author_name,
                "execution_mode": "workflow",
                "workflow_id": str(workflow_id),
                "checkpoint_thread_id": str(workflow_id),
                **trace_author_metadata(author),
                **(metadata or {}),
            },
        }

    @staticmethod
    def _checkpoint_config(workflow_id: UUID, checkpoint_id: str) -> RunnableConfig:
        config = MasterOrchestratorAgent._config(workflow_id)
        config["configurable"] = {
            "thread_id": str(workflow_id),
            "checkpoint_id": checkpoint_id,
        }
        config["metadata"] = {
            **dict(config.get("metadata", {})),
            "checkpoint_id": checkpoint_id,
            "checkpoint_operation": "replay",
        }
        return config

    @staticmethod
    def _trace_metadata(
        context: ExecutionContext | None,
        task_payload: dict[str, Any],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if context is not None:
            metadata.update(
                {
                    "run_id": context.run_id,
                    "workflow_id": context.workflow_id or "",
                    "assignment_id": context.assignment_id or "",
                    "attempt_number": context.attempt_number,
                }
            )
        task_id = task_payload.get("task_id")
        if task_id:
            metadata["task_id"] = str(task_id)
        return metadata

    def _format_result(
        self,
        workflow_id: UUID,
        graph_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        projected = self.state_service.get_current(workflow_id)
        pending_input: dict[str, Any] | None = None
        if graph_result is not None:
            interrupts = graph_result.get("__interrupt__", ())
            if interrupts:
                value = getattr(interrupts[0], "value", interrupts[0])
                pending_input = value if isinstance(value, dict) else {"prompt": str(value)}
        if pending_input is None and projected.status in {
            WorkflowStatus.AWAITING_PLAN_APPROVAL,
            WorkflowStatus.AWAITING_TASK_APPROVAL,
            WorkflowStatus.AWAITING_AGENT_APPROVAL,
        }:
            approval = projected.metadata.get("pending_approval", {})
            pending_input = {
                "type": "human_approval",
                "approval": approval,
                "prompt": approval.get("prompt", "Human approval is required."),
                "options": [
                    {"label": option.title(), "value": str(option)}
                    for option in approval.get("options", ["APPROVE", "REVISE", "REJECT"])
                ],
                **approval.get("context", {}),
            }
        if pending_input is None and projected.status == WorkflowStatus.WAITING_FOR_AGENT:
            pending_input = {
                "type": "agent_result",
                "workflow_id": str(workflow_id),
                "task": projected.metadata.get("current_task", {}),
            }
        return {
            "workflow_id": str(projected.workflow_id),
            "conversation_id": projected.conversation_id,
            "status": projected.status,
            "plan": projected.metadata.get("plan"),
            "current_task": projected.metadata.get("current_task"),
            "pending_input": pending_input,
            "assigned_agents": projected.assigned_agents,
            "task_results": projected.metadata.get("task_results", []),
            "rerun_of_workflow_id": projected.metadata.get("rerun_of_workflow_id"),
            "rerun_of_task_id": projected.metadata.get("rerun_of_task_id"),
        }

    async def checkpoint_history(self, workflow_id: UUID) -> list[dict[str, Any]]:
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                workflow_id,
                "checkpoint history",
                author.author_name,
            ),
            inputs={"workflow_id": str(workflow_id)},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                workflow_id=workflow_id,
                checkpoint_thread_id=workflow_id,
                checkpoint_operation="history",
                **trace_author_metadata(author),
            ),
            tags=["workflow", "checkpoint", self.agent_name],
        ) as run:
            history = []
            async for snapshot in self.graph.aget_state_history(self._config(workflow_id)):
                history.append(
                    {
                        "checkpoint_id": snapshot.config.get("configurable", {}).get(
                            "checkpoint_id"
                        ),
                        "created_at": snapshot.created_at,
                        "next": list(snapshot.next),
                        "metadata": dict(snapshot.metadata or {}),
                    }
                )
            if run is not None:
                run.end(outputs={"checkpoint_count": len(history)})
            return history

    async def replay_checkpoint(
        self,
        workflow_id: UUID,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        """Inspect a historical state without re-emitting event side effects."""

        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                workflow_id,
                f"checkpoint replay {checkpoint_id}",
                author.author_name,
            ),
            inputs={"workflow_id": str(workflow_id), "checkpoint_id": checkpoint_id},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                workflow_id=workflow_id,
                checkpoint_thread_id=workflow_id,
                checkpoint_id=checkpoint_id,
                checkpoint_operation="replay",
                **trace_author_metadata(author),
            ),
            tags=["workflow", "checkpoint", "replay", self.agent_name],
        ) as run:
            snapshot = await self.graph.aget_state(
                self._checkpoint_config(workflow_id, checkpoint_id)
            )
            if not snapshot.values:
                raise ValueError(f"Checkpoint {checkpoint_id!r} was not found.")
            response = {
                "mode": "read_only_replay",
                "workflow_id": str(workflow_id),
                "checkpoint_id": checkpoint_id,
                "next": list(snapshot.next),
                "state": {
                    key: value
                    for key, value in dict(snapshot.values).items()
                    if key != "messages"
                },
                "metadata": dict(snapshot.metadata or {}),
            }
            if run is not None:
                run.end(outputs={"next": response["next"]})
            return response

    async def fork_checkpoint(
        self,
        workflow_id: UUID,
        checkpoint_id: str,
        *,
        new_workflow_id: UUID,
        state_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Copy a checkpoint into an isolated diagnostic namespace."""

        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        with agentmesh_span(
            agentmesh_run_name(
                "WorkFlow",
                workflow_id,
                f"checkpoint fork {checkpoint_id}",
                author.author_name,
            ),
            inputs={
                "workflow_id": str(workflow_id),
                "checkpoint_id": checkpoint_id,
                "new_workflow_id": str(new_workflow_id),
                "state_update_keys": sorted(state_updates or {}),
            },
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                workflow_id=workflow_id,
                checkpoint_thread_id=workflow_id,
                checkpoint_id=checkpoint_id,
                checkpoint_operation="fork",
                new_workflow_id=new_workflow_id,
                **trace_author_metadata(author),
            ),
            tags=["workflow", "checkpoint", "fork", self.agent_name],
        ) as run:
            snapshot = await self.graph.aget_state(
                self._checkpoint_config(workflow_id, checkpoint_id)
            )
            if not snapshot.values:
                raise ValueError(f"Checkpoint {checkpoint_id!r} was not found.")
            values = {
                **dict(snapshot.values),
                "workflow_id": str(new_workflow_id),
                **(state_updates or {}),
            }
            fork_config = await self.graph.aupdate_state(
                self._config(
                    new_workflow_id,
                    {
                        "source_workflow_id": str(workflow_id),
                        "source_checkpoint_id": checkpoint_id,
                        "fork_mode": "diagnostic",
                    },
                ),
                values,
                as_node=self._snapshot_node(snapshot.metadata),
            )
            response = {
                "mode": "diagnostic_fork",
                "source_workflow_id": str(workflow_id),
                "source_checkpoint_id": checkpoint_id,
                "workflow_id": str(new_workflow_id),
                "checkpoint_id": fork_config.get("configurable", {}).get("checkpoint_id"),
            }
            if run is not None:
                run.end(outputs={"checkpoint_id": response["checkpoint_id"]})
            return response

    @staticmethod
    def _snapshot_node(metadata: Mapping[str, Any] | None) -> str | None:
        writes = (metadata or {}).get("writes", {})
        if isinstance(writes, dict) and writes:
            return str(next(reversed(writes)))
        return None

    def graph_mermaid(self) -> str:
        return str(self.graph.get_graph().draw_mermaid())
