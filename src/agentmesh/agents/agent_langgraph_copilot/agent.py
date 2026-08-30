from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_store
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, RetryPolicy, interrupt

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.execution import ExecutionContext
from agentmesh.core.frameworks.langgraph import load_opt_in_memories, provider_messages
from agentmesh.core.models.exceptions import ModelProviderError, ValidationError
from agentmesh.core.observability import (
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
)
from agentmesh.core.providers import TextCompletionClient


class ConversationState(MessagesState, total=False):
    task_kind: str
    task_plan: list[str]
    draft_reply: str
    draft_message_id: str
    final_reply: str
    approval_required: bool
    approval_decision: str
    approval_feedback: str
    approved: bool
    rejected: bool
    revision_count: int
    max_revisions: int
    quality_score: float
    evaluation_attempts: int
    max_evaluation_attempts: int
    evaluation_feedback: str
    evaluation_tokens_used: int
    max_evaluation_tokens: int
    evaluation_deadline_at: str
    memory_user_id: str
    memory_opt_in: bool
    memory_updates: dict[str, str]
    memory_delete_keys: list[str]
    long_term_memories: list[dict[str, Any]]


class ConversationAgent(BaseAgent):
    """Checkpointed LangGraph worker with resumable output approval."""

    def __init__(
        self,
        agent_name: str = "langgraph-copilot",
        *,
        auto_register: bool = True,
        llm_client: TextCompletionClient | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        store: BaseStore | None = None,
        max_revisions: int = 2,
        max_evaluation_attempts: int = 3,
        max_evaluation_tokens: int = 12_000,
        evaluation_timeout_seconds: float = 45.0,
        long_term_memory_enabled: bool = False,
        memory_retention_days: int = 30,
    ) -> None:
        self.llm_client = llm_client
        self.checkpointer = checkpointer or MemorySaver()
        self.store = store or InMemoryStore()
        self.max_revisions = max_revisions
        self.max_evaluation_attempts = max_evaluation_attempts
        self.max_evaluation_tokens = max_evaluation_tokens
        self.evaluation_timeout_seconds = evaluation_timeout_seconds
        self.long_term_memory_enabled = long_term_memory_enabled
        self.memory_retention_days = memory_retention_days
        self.last_successful_model_call: str | None = None
        super().__init__(
            agent_name,
            auto_register=auto_register,
            endpoint=os.getenv("AGENT_ENDPOINT", "http://localhost:8001"),
            capabilities=["CHAT", "DRAFT", "REVIEW"],
            skills=["conversation", "drafting", "output_review"],
            description="LangGraph conversation and review agent with resumable output approval",
            metadata={
                "framework": "langgraph",
                "human_in_loop": True,
                "approval_modes": ["output_review"],
                "supports_resume": True,
                "supports_time_travel": True,
                "long_term_memory": "opt_in",
            },
        )
        self.llm_model = (
            llm_client.model
            if llm_client is not None
            else os.getenv("LANGGRAPH_MODEL", "local-langgraph-agent")
        )
        self.graph = self._build_graph()

    def _build_graph(
        self,
    ) -> CompiledStateGraph[ConversationState, None, ConversationState, ConversationState]:
        graph = StateGraph(ConversationState)
        graph.add_node("validate_input", self._validate_input)
        graph.add_node("load_context", self._load_context)
        graph.add_node("classify_task", self._classify_task)
        graph.add_node("plan_task", self._plan_task)
        graph.add_node(
            "generate_response",
            self._generate_response,
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_interval=0.5,
                backoff_factor=2.0,
                max_interval=8.0,
                jitter=True,
                retry_on=ModelProviderError,
            ),
        )
        graph.add_node("validate_output", self._validate_output)
        graph.add_node("evaluate_output", self._evaluate_output)
        graph.add_node("human_approval", self._human_approval)
        graph.add_node("finalize", self._finalize)
        graph.add_node("reject", self._reject)

        graph.add_edge(START, "validate_input")
        graph.add_edge("validate_input", "load_context")
        graph.add_edge("load_context", "classify_task")
        graph.add_conditional_edges(
            "classify_task",
            lambda state: state.get("task_kind", "simple"),
            {"simple": "generate_response", "multi_step": "plan_task"},
        )
        graph.add_edge("plan_task", "generate_response")
        graph.add_edge("generate_response", "validate_output")
        graph.add_edge("validate_output", "evaluate_output")
        graph.add_conditional_edges(
            "evaluate_output",
            self._evaluation_route,
            {
                "revise": "generate_response",
                "approval": "human_approval",
                "complete": "finalize",
            },
        )
        graph.add_conditional_edges(
            "human_approval",
            self._approval_route,
            {"approve": "finalize", "revise": "generate_response", "reject": "reject"},
        )
        graph.add_edge("finalize", END)
        graph.add_edge("reject", END)
        return graph.compile(checkpointer=self.checkpointer, store=self.store)

    @staticmethod
    def _validate_input(state: ConversationState) -> dict[str, Any]:
        messages = state.get("messages", [])
        if not messages or not str(messages[-1].content).strip():
            raise ValidationError("A conversation task must include at least one message.")
        return {}

    def _load_context(self, state: ConversationState) -> dict[str, Any]:
        result: dict[str, Any] = {
            "revision_count": int(state.get("revision_count", 0)),
            "max_revisions": int(state.get("max_revisions", 2)),
            "evaluation_attempts": int(state.get("evaluation_attempts", 0)),
            "max_evaluation_attempts": int(
                state.get("max_evaluation_attempts", self.max_evaluation_attempts)
            ),
            "evaluation_tokens_used": int(state.get("evaluation_tokens_used", 0)),
            "max_evaluation_tokens": int(
                state.get("max_evaluation_tokens", self.max_evaluation_tokens)
            ),
        }
        result["long_term_memories"] = load_opt_in_memories(
            get_store(),
            agent_id=self.agent_name,
            enabled=self.long_term_memory_enabled,
            user_id=state.get("memory_user_id", ""),
            opt_in=state.get("memory_opt_in", False),
            updates=state.get("memory_updates", {}),
            delete_keys=state.get("memory_delete_keys", []),
            retention_days=self.memory_retention_days,
        )
        return result

    @staticmethod
    def _classify_task(state: ConversationState) -> dict[str, Any]:
        prompt_words = set(str(state["messages"][-1].content).lower().split())
        multi_step_terms = {
            "plan",
            "compare",
            "research",
            "design",
            "strategy",
            "evaluate",
            "analyze",
        }

        is_multi_step = bool(prompt_words & multi_step_terms)

        return {"task_kind": "multi_step" if is_multi_step else "simple"}

    @staticmethod
    def _plan_task(state: ConversationState) -> dict[str, Any]:
        del state
        return {
            "task_plan": [
                "Identify the requested outcome and constraints.",
                "Develop a concise, actionable response.",
                "Review the response for completeness and unsupported claims.",
            ]
        }

    def _generate_response(self, state: ConversationState) -> dict[str, Any]:
        reply = self._generate_reply(
            state["messages"],
            feedback=(
                state.get("approval_feedback", "").strip()
                or state.get("evaluation_feedback", "").strip()
            ),
            plan=state.get("task_plan", []),
            memories=state.get("long_term_memories", []),
        )
        draft_message_id = state.get("draft_message_id") or str(uuid4())
        return {
            "messages": [AIMessage(content=reply, id=draft_message_id)],
            "draft_reply": reply,
            "draft_message_id": draft_message_id,
            "evaluation_tokens_used": int(state.get("evaluation_tokens_used", 0))
            + len(reply.split()),
            "approval_decision": "",
            "approval_feedback": "",
        }

    @staticmethod
    def _validate_output(state: ConversationState) -> dict[str, Any]:
        draft = state.get("draft_reply", "").strip()
        if not draft:
            raise ModelProviderError("The model produced an empty draft.")
        return {"draft_reply": draft}

    @staticmethod
    def _evaluate_output(state: ConversationState) -> dict[str, Any]:
        word_count = len(state.get("draft_reply", "").split())
        score = 1.0 if word_count >= 4 else 0.5
        return {
            "quality_score": score,
            "evaluation_attempts": int(state.get("evaluation_attempts", 0)) + 1,
            "evaluation_feedback": (
                "Expand the response with a concrete, complete answer." if score < 0.8 else ""
            ),
        }

    @staticmethod
    def _evaluation_route(state: ConversationState) -> str:
        deadline = datetime.fromisoformat(
            state.get("evaluation_deadline_at", datetime.now(UTC).isoformat())
        )
        if (
            state.get("quality_score", 0.0) < 0.8
            and state.get("evaluation_attempts", 0) < state.get("max_evaluation_attempts", 3)
            and state.get("evaluation_tokens_used", 0) < state.get("max_evaluation_tokens", 12_000)
            and datetime.now(UTC) < deadline
        ):
            return "revise"
        return "approval" if state.get("approval_required", False) else "complete"

    @staticmethod
    def _human_approval(state: ConversationState) -> dict[str, Any]:
        response = interrupt(
            {
                "type": "agent_output_approval",
                "prompt": "Review the LangGraph Copilot draft before accepting it.",
                "draft_reply": state.get("draft_reply", ""),
                "options": ["approve", "revise", "reject"],
                "revision_count": state.get("revision_count", 0),
                "max_revisions": state.get("max_revisions", 2),
            }
        )
        if isinstance(response, dict):
            decision = str(response.get("decision", "")).strip().lower()
            feedback = str(response.get("feedback", "")).strip()
        else:
            decision = str(response).strip().lower()
            feedback = ""
        if decision not in {"approve", "revise", "reject"}:
            raise ValidationError("Agent approval decision must be approve, revise, or reject.")
        revision_count = state.get("revision_count", 0)
        if decision == "revise" and revision_count >= state.get("max_revisions", 2):
            raise ValidationError("The maximum number of output revisions has been reached.")
        return {
            "approval_decision": decision,
            "approval_feedback": feedback,
            "revision_count": revision_count + int(decision == "revise"),
            "approved": decision == "approve",
            "rejected": decision == "reject",
        }

    @staticmethod
    def _approval_route(state: ConversationState) -> str:
        return state.get("approval_decision", "reject")

    @staticmethod
    def _finalize(state: ConversationState) -> dict[str, Any]:
        return {"final_reply": state.get("draft_reply", ""), "approved": True}

    @staticmethod
    def _reject(state: ConversationState) -> dict[str, Any]:
        return {"final_reply": "", "approved": False, "rejected": True}

    def start_conversation(
        self,
        user_message: str,
        *,
        thread_id: str,
        approval_required: bool = True,
    ) -> dict[str, Any]:
        result = self.graph.invoke(
            ConversationState(
                messages=[HumanMessage(content=user_message)],
                approval_required=approval_required,
                max_revisions=self.max_revisions,
                max_evaluation_attempts=self.max_evaluation_attempts,
                evaluation_attempts=0,
                evaluation_feedback="",
                evaluation_tokens_used=0,
                max_evaluation_tokens=self.max_evaluation_tokens,
                evaluation_deadline_at=(
                    datetime.now(UTC) + timedelta(seconds=self.evaluation_timeout_seconds)
                ).isoformat(),
                draft_message_id="",
            ),
            config=self._config(thread_id),
        )
        return self._format_graph_result(dict(result), thread_id)

    async def astart_conversation(
        self,
        user_message: str,
        *,
        thread_id: str,
        approval_required: bool = True,
        memory_user_id: str = "",
        memory_opt_in: bool = False,
        memory_updates: dict[str, str] | None = None,
        memory_delete_keys: list[str] | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self.graph.ainvoke(
            ConversationState(
                messages=[HumanMessage(content=user_message)],
                approval_required=approval_required,
                max_revisions=self.max_revisions,
                max_evaluation_attempts=self.max_evaluation_attempts,
                evaluation_attempts=0,
                evaluation_feedback="",
                evaluation_tokens_used=0,
                max_evaluation_tokens=self.max_evaluation_tokens,
                evaluation_deadline_at=(
                    datetime.now(UTC) + timedelta(seconds=self.evaluation_timeout_seconds)
                ).isoformat(),
                draft_message_id="",
                memory_user_id=memory_user_id,
                memory_opt_in=memory_opt_in,
                memory_updates=memory_updates or {},
                memory_delete_keys=memory_delete_keys or [],
            ),
            config=self._config(thread_id, trace_metadata),
        )
        return self._format_graph_result(dict(result), thread_id)

    def resume_conversation(
        self,
        thread_id: str,
        decision: str,
        feedback: str = "",
    ) -> dict[str, Any]:
        snapshot = self.graph.get_state(self._config(thread_id))
        if not snapshot.values or not snapshot.next:
            raise ValueError(f"No pending conversation for thread {thread_id!r}.")
        command: Command[Any] = Command(resume={"decision": decision, "feedback": feedback})
        result = self.graph.invoke(
            command,
            config=self._config(thread_id),
        )
        return self._format_graph_result(dict(result), thread_id)

    async def aresume_conversation(
        self,
        thread_id: str,
        decision: str,
        feedback: str = "",
        trace_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self._config(thread_id))
        if not snapshot.values or not snapshot.next:
            raise ValueError(f"No pending conversation for thread {thread_id!r}.")
        result = await self.graph.ainvoke(
            Command(resume={"decision": decision, "feedback": feedback}),
            config=self._config(thread_id, trace_metadata),
        )
        return self._format_graph_result(dict(result), thread_id)

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        nested_payload = task_payload.get("payload", {})
        if not isinstance(nested_payload, dict):
            nested_payload = {}
        resume_thread_id = str(
            task_payload.get("resume_thread_id") or nested_payload.get("resume_thread_id", "")
        ).strip()
        if resume_thread_id:
            return self.resume_conversation(
                resume_thread_id,
                str(
                    task_payload.get("approval_decision")
                    or nested_payload.get("approval_decision", "")
                ),
                str(
                    task_payload.get("approval_feedback")
                    or nested_payload.get("approval_feedback", "")
                ),
            )

        explicit_approval = task_payload.get(
            "approval_required", nested_payload.get("approval_required")
        )
        approval_required = (
            bool(explicit_approval)
            if explicit_approval is not None
            else bool(task_payload.get("task_id"))
        )
        thread_id = str(
            task_payload.get("thread_id")
            or nested_payload.get("thread_id")
            or self._task_thread_id(task_payload)
        )
        result = self.start_conversation(
            self._task_prompt(task_payload),
            thread_id=thread_id,
            approval_required=approval_required,
        )
        return {"agent": self.agent_name, "model": self.llm_model, **result}

    def run_conversation(self, user_message: str) -> dict[str, Any]:
        return self.run_task({"messages": [user_message], "approval_required": False})

    async def arun_task(
        self,
        task_payload: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        nested_payload = task_payload.get("payload", {})
        if not isinstance(nested_payload, dict):
            nested_payload = {}
        resume_thread_id = str(
            task_payload.get("resume_thread_id") or nested_payload.get("resume_thread_id", "")
        ).strip()
        if resume_thread_id:
            return await self.aresume_conversation(
                resume_thread_id,
                str(
                    task_payload.get("approval_decision")
                    or nested_payload.get("approval_decision", "")
                ),
                str(
                    task_payload.get("approval_feedback")
                    or nested_payload.get("approval_feedback", "")
                ),
                trace_metadata=self._trace_metadata(context, task_payload),
            )

        explicit_approval = task_payload.get(
            "approval_required", nested_payload.get("approval_required")
        )
        thread_id = str(
            task_payload.get("thread_id")
            or nested_payload.get("thread_id")
            or self._task_thread_id(task_payload)
        )
        raw_updates = task_payload.get("memory_updates", nested_payload.get("memory_updates", {}))
        raw_deletes = task_payload.get(
            "memory_delete_keys", nested_payload.get("memory_delete_keys", [])
        )
        result = await self.astart_conversation(
            self._task_prompt(task_payload),
            thread_id=thread_id,
            approval_required=(
                bool(explicit_approval)
                if explicit_approval is not None
                else bool(task_payload.get("task_id"))
            ),
            memory_user_id=str(task_payload.get("user_id") or nested_payload.get("user_id", "")),
            memory_opt_in=bool(
                task_payload.get("memory_opt_in", nested_payload.get("memory_opt_in", False))
            ),
            memory_updates=(
                {str(key): str(value) for key, value in raw_updates.items()}
                if isinstance(raw_updates, dict)
                else {}
            ),
            memory_delete_keys=(
                [str(key) for key in raw_deletes] if isinstance(raw_deletes, list) else []
            ),
            trace_metadata=self._trace_metadata(context, task_payload),
        )
        return {"agent": self.agent_name, "model": self.llm_model, **result}

    def _generate_reply(
        self,
        messages: Sequence[BaseMessage],
        *,
        feedback: str,
        plan: list[str],
        memories: list[dict[str, Any]],
    ) -> str:
        prompt = str(messages[-1].content)
        if self.llm_client is None:
            suffix = f" Revision feedback: {feedback}" if feedback else ""
            return f"I can help with: {prompt}. This is the local LangGraph response.{suffix}"
        outline = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(plan))
        user_content = f"Task: {prompt}"
        if outline:
            user_content = f"{user_content}\n\nExecution outline:\n{outline}"
        if feedback:
            user_content = f"{user_content}\n\nHuman revision feedback: {feedback}"
        if memories:
            memory_text = "\n".join(
                f"- {item.get('name')}: {item.get('value')}" for item in memories
            )
            user_content = f"{user_content}\n\nApproved user preferences:\n{memory_text}"
        reply = self.llm_client.create_text_completion(
            messages=[
                *provider_messages(
                    [
                        SystemMessage(
                            content=(
                                "You are the LangGraph Copilot worker in AgentMesh. Produce a "
                                "useful, concise task result. Respect supplied constraints and "
                                "never claim actions or sources that you did not actually use."
                            )
                        ),
                        *messages[:-1],
                    ]
                ),
                {"role": "user", "content": user_content},
            ]
        )
        self.last_successful_model_call = datetime.now(UTC).isoformat()
        return reply

    async def checkpoint_history(self, thread_id: str) -> list[dict[str, Any]]:
        with agentmesh_span(
            agentmesh_run_name(
                "Direct",
                thread_id,
                "checkpoint history",
                self.agent_name,
            ),
            inputs={"thread_id": thread_id},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                thread_id=thread_id,
                checkpoint_thread_id=thread_id,
                checkpoint_operation="history",
            ),
            tags=["checkpoint", "langgraph-agent", self.agent_name],
        ) as run:
            history = []
            async for snapshot in self.graph.aget_state_history(self._config(thread_id)):
                configurable = snapshot.config.get("configurable", {})
                history.append(
                    {
                        "checkpoint_id": configurable.get("checkpoint_id"),
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
        thread_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        with agentmesh_span(
            agentmesh_run_name(
                "Direct",
                thread_id,
                f"checkpoint replay {checkpoint_id}",
                self.agent_name,
            ),
            inputs={"thread_id": thread_id, "checkpoint_id": checkpoint_id},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                thread_id=thread_id,
                checkpoint_thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                checkpoint_operation="replay",
            ),
            tags=["checkpoint", "replay", "langgraph-agent", self.agent_name],
        ) as run:
            config = self._checkpoint_config(thread_id, checkpoint_id)
            result = await self.graph.ainvoke(None, config=config)
            response = self._format_graph_result(dict(result), thread_id)
            if run is not None:
                run.end(outputs={"status": response.get("status")})
            return response

    async def fork_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        *,
        new_thread_id: str,
        state_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with agentmesh_span(
            agentmesh_run_name(
                "Direct",
                thread_id,
                f"checkpoint fork {checkpoint_id}",
                self.agent_name,
            ),
            inputs={
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "new_thread_id": new_thread_id,
                "state_update_keys": sorted(state_updates or {}),
            },
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                thread_id=thread_id,
                checkpoint_thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                checkpoint_operation="fork",
                new_thread_id=new_thread_id,
            ),
            tags=["checkpoint", "fork", "langgraph-agent", self.agent_name],
        ) as run:
            snapshot = await self.graph.aget_state(
                self._checkpoint_config(thread_id, checkpoint_id)
            )
            if not snapshot.values:
                raise ValueError(f"Checkpoint {checkpoint_id!r} was not found.")
            values = {**dict(snapshot.values), **(state_updates or {})}
            fork_config = await self.graph.aupdate_state(
                self._config(new_thread_id),
                values,
                as_node=self._snapshot_node(snapshot.metadata),
            )
            response = {
                "source_thread_id": thread_id,
                "source_checkpoint_id": checkpoint_id,
                "thread_id": new_thread_id,
                "checkpoint_id": fork_config.get("configurable", {}).get("checkpoint_id"),
            }
            if run is not None:
                run.end(outputs={"checkpoint_id": response["checkpoint_id"]})
            return response

    def graph_mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()

    def _format_graph_result(self, result: dict[str, Any], thread_id: str) -> dict[str, Any]:
        interrupts = result.get("__interrupt__", ())
        if interrupts:
            value = getattr(interrupts[0], "value", interrupts[0])
            payload = value if isinstance(value, dict) else {"prompt": str(value)}
            return {
                "status": "AWAITING_APPROVAL",
                "thread_id": thread_id,
                "interrupt": payload,
                "draft_reply": payload.get("draft_reply", ""),
                "prompt": payload.get("prompt", "Review the generated output."),
                "options": payload.get("options", ["approve", "revise", "reject"]),
                "llm_model": self.llm_model,
            }
        status = "REJECTED" if result.get("rejected") else "COMPLETED"
        public_result = {
            key: value for key, value in result.items() if key not in {"messages", "__interrupt__"}
        }
        return {
            "status": status,
            "thread_id": thread_id,
            "llm_model": self.llm_model,
            **public_result,
        }

    @staticmethod
    def _task_prompt(task_payload: dict[str, Any]) -> str:
        messages = task_payload.get("messages")
        if isinstance(messages, list) and messages:
            return str(messages[-1])
        nested_payload = task_payload.get("payload", {})
        if not isinstance(nested_payload, dict):
            nested_payload = {}
        goal = str(nested_payload.get("goal", ""))
        description = str(task_payload.get("description", "")).strip()
        prompt = "\n\n".join(part for part in [description, goal] if part)
        if not prompt:
            raise ValidationError("A LangGraph task requires messages, a goal, or a description.")
        return prompt

    @staticmethod
    def _task_thread_id(task_payload: dict[str, Any]) -> str:
        workflow_id = str(task_payload.get("workflow_id", "workflow"))
        task_id = str(task_payload.get("task_id", uuid4()))
        return f"agent:{workflow_id}:{task_id}"

    def _config(
        self,
        thread_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> RunnableConfig:
        trace_metadata = {
            "agent_id": self.agent_name,
            "thread_id": thread_id,
            "execution_mode": (metadata or {}).get("execution_mode", "direct"),
            "checkpoint_thread_id": thread_id,
            **(metadata or {}),
        }
        mode = "WorkFlow" if trace_metadata["execution_mode"] == "workflow" else "Direct"
        return {
            "configurable": {"thread_id": thread_id},
            "metadata": trace_metadata,
            "run_name": agentmesh_run_name(
                mode,
                thread_id,
                "langgraph agent",
                self.agent_name,
            ),
            "tags": ["agentmesh", "langgraph-agent", self.agent_name],
        }

    @staticmethod
    def _checkpoint_config(thread_id: str, checkpoint_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            },
            "metadata": {
                "agent_id": "langgraph-copilot",
                "thread_id": thread_id,
                "checkpoint_thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "execution_mode": "checkpoint_api",
            },
            "run_name": agentmesh_run_name(
                "Direct",
                thread_id,
                f"checkpoint replay {checkpoint_id}",
                "langgraph-copilot",
            ),
            "tags": ["agentmesh", "checkpoint", "langgraph-agent"],
        }

    @staticmethod
    def _trace_metadata(
        context: ExecutionContext | None,
        task_payload: dict[str, Any],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        task_id = task_payload.get("task_id")
        if task_id:
            metadata["task_id"] = str(task_id)
        if context is not None:
            metadata.update(
                {
                    "run_id": context.run_id,
                    "source": context.source,
                    "execution_mode": (
                        "workflow" if context.source == "assignment" else context.source
                    ),
                    "attempt_number": context.attempt_number,
                }
            )
            if context.workflow_id:
                metadata["workflow_id"] = context.workflow_id
            if context.assignment_id:
                metadata["assignment_id"] = context.assignment_id
                metadata["assignment_event_id"] = context.assignment_id
        return metadata

    @staticmethod
    def _snapshot_node(metadata: Mapping[str, Any] | None) -> str | None:
        writes = (metadata or {}).get("writes", {})
        if isinstance(writes, dict) and writes:
            return str(next(reversed(writes)))
        return None
