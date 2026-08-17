from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agentmesh.agents.agent_langgraph_orchestrator_supervisor.planner import (
    CapabilityWorkflowPlanner,
    WorkflowPlanner,
)
from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.core.agent_card import AgentCard
from agentmesh.core.exceptions import (
    AgentRegistryError,
    ValidationError,
    WorkflowConflictError,
)
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
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService

ORCHESTRATOR_AGENT_ID = "orchestrator-supervisor-agent"


class MasterWorkflowState(TypedDict, total=False):
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
    task_results: list[dict[str, Any]]
    task_result_status: str
    assignment_event_id: str


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
        agent_stale_seconds: float = 180.0,
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
        self.agent_stale_seconds = agent_stale_seconds
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
            raise ValidationError(
                "An orchestrator task requires a goal, description, or message."
            )

        conversation_id = str(
            task_payload.get("conversation_id")
            or nested_payload.get("conversation_id")
            or f"orchestrator-{uuid4()}"
        ).strip()
        raw_workflow_id = task_payload.get("workflow_id") or nested_payload.get(
            "workflow_id"
        )
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
        )

    @staticmethod
    def _last_message(messages: Any) -> str:
        if not isinstance(messages, list) or not messages:
            return ""
        message = messages[-1]
        if isinstance(message, dict):
            return str(message.get("content", ""))
        return str(message)

    def _build_graph(self) -> Any:
        builder = StateGraph(MasterWorkflowState)
        builder.add_node("discover_agents", self._discover_agents)
        builder.add_node("create_plan", self._create_plan)
        builder.add_node("request_plan_approval", self._request_plan_approval)
        builder.add_node("review_plan", self._review_plan)
        builder.add_node("prepare_task", self._prepare_task)
        builder.add_node("review_task", self._review_task)
        builder.add_node("dispatch_task", self._dispatch_task)
        builder.add_node("wait_for_task_result", self._wait_for_task_result)
        builder.add_node("advance_task", self._advance_task)
        builder.add_node("complete_workflow", self._complete_workflow)
        builder.add_node("fail_workflow", self._fail_workflow)
        builder.add_node("cancel_workflow", self._cancel_workflow)

        builder.add_edge(START, "discover_agents")
        builder.add_edge("discover_agents", "create_plan")
        builder.add_edge("create_plan", "request_plan_approval")
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
            {"COMPLETED": "advance_task", "FAILED": "fail_workflow"},
        )
        builder.add_conditional_edges(
            "advance_task",
            self._advance_route,
            {"NEXT": "prepare_task", "COMPLETE": "complete_workflow"},
        )
        builder.add_edge("complete_workflow", END)
        builder.add_edge("fail_workflow", END)
        builder.add_edge("cancel_workflow", END)
        return builder.compile(checkpointer=self.checkpointer)

    def start_workflow(
        self,
        conversation_id: str,
        goal: str,
        *,
        workflow_id: UUID | None = None,
        preferred_agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start planning and run until the plan approval checkpoint."""

        resolved_workflow_id = workflow_id or uuid4()
        if self.event_service.replay(resolved_workflow_id):
            raise WorkflowConflictError(f"Workflow {resolved_workflow_id} already exists.")
        self._emit_raw(
            conversation_id=conversation_id,
            workflow_id=resolved_workflow_id,
            event_type="WORKFLOW_STARTED",
            payload={"goal": goal},
        )
        try:
            result = self.graph.invoke(
                {
                    "conversation_id": conversation_id,
                    "workflow_id": str(resolved_workflow_id),
                    "goal": goal,
                    "preferred_agent_ids": preferred_agent_ids or [],
                    "plan_version": 0,
                    "task_index": 0,
                    "task_results": [],
                    "feedback": "",
                },
                config=self._config(resolved_workflow_id),
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
            config=self._config(workflow_id),
        )
        return self._format_result(workflow_id, result)

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
        if normalized_status not in {"COMPLETED", "FAILED"}:
            raise ValidationError("Task result status must be COMPLETED or FAILED.")
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

    def get_workflow(self, workflow_id: UUID) -> dict[str, Any]:
        """Return event-projected workflow status without mutating execution."""

        return self._format_result(workflow_id, None)

    def _discover_agents(self, state: MasterWorkflowState) -> dict[str, Any]:
        cards = self.registry_service.list_agents()
        online_cards = [
            card
            for card in cards
            if card.status == "online"
            and self._is_worker_agent(card)
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
        self._emit(state, "PLAN_APPROVAL_REQUESTED", {"approval": payload})
        return {"pending_approval": payload}

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
        assignment = self._emit(
            state,
            "TASK_ASSIGNED",
            {"task": task.model_dump(mode="json"), "task_type": task.required_capability},
            routing_mode=RoutingMode.DIRECTED,
            target_agent=task.agent_id,
        )
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
        if status not in {"COMPLETED", "FAILED"}:
            raise ValidationError("Agent result status must be COMPLETED or FAILED.")
        event_type = "TASK_COMPLETED" if status == "COMPLETED" else "TASK_FAILED"
        event_payload = {
            "task_id": str(task.task_id),
            "assignment_event_id": state["assignment_event_id"],
            "result": response.get("result", {}),
        }
        self._emit(
            state,
            event_type,
            event_payload,
            source_agent=task.agent_id,
            causation_id=UUID(state["assignment_event_id"]),
        )
        task_results = [*state.get("task_results", []), event_payload]
        return {"task_result_status": status, "task_results": task_results}

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
        response = interrupt(
            {
                "type": "human_approval",
                "approval": approval.model_dump(mode="json"),
                "prompt": approval.prompt,
                "options": [
                    {"label": option.title(), "value": str(option)} for option in approval.options
                ],
                **approval.context,
            }
        )
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
    def _config(workflow_id: UUID) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": str(workflow_id)}}

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
        }
