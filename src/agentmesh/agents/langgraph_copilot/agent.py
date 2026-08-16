from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from agentmesh.agents.base import BaseAgent


class ConversationState(TypedDict, total=False):
    messages: list[str]
    draft_reply: str
    approved: bool
    final_reply: str


class ConversationAgent(BaseAgent):
    """A small LangGraph-based conversation agent with a human approval checkpoint."""

    def __init__(
        self,
        agent_name: str = "langgraph-copilot",
        *,
        auto_register: bool = True,
    ) -> None:
        super().__init__(
            agent_name,
            auto_register=auto_register,
            endpoint=os.getenv("AGENT_ENDPOINT", "http://localhost:8001"),
            capabilities=["CHAT", "REVIEW"],
            skills=["conversation", "human_approval"],
            description="Conversation agent with human-in-the-loop approval",
        )
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(ConversationState)

        def draft_response(state: dict[str, Any]) -> dict[str, Any]:
            last_message = state.get("messages", [])[-1] if state.get("messages") else ""
            reply = f"I can help with: {last_message}. Please confirm before I send the final answer."
            return {"draft_reply": reply}

        def human_approval(state: dict[str, Any]) -> dict[str, Any]:
            draft_reply = state.get("draft_reply", "")
            approval = interrupt({
                "type": "human_approval",
                "prompt": "Review the draft response before sending it.",
                "draft_reply": draft_reply,
                "options": ["approve", "reject"],
            })
            decision = str(approval).strip().lower()
            return {
                "approved": decision in {"approve", "approved", "yes"},
                "draft_reply": draft_reply,
            }

        def finalize(state: dict[str, Any]) -> dict[str, Any]:
            if state.get("approved"):
                return {"final_reply": state.get("draft_reply", "")}
            return {"final_reply": "I paused the response and waiting for your approval."}

        graph.add_node("draft_response", draft_response)
        graph.add_node("human_approval", human_approval)
        graph.add_node("finalize", finalize)
        graph.set_entry_point("draft_response")
        graph.add_edge("draft_response", "human_approval")
        graph.add_edge("human_approval", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=self.checkpointer)

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def _format_graph_result(self, result: dict[str, Any], thread_id: str) -> dict[str, Any]:
        interrupts = result.get("__interrupt__", ())
        if interrupts:
            interrupt_value = getattr(interrupts[0], "value", interrupts[0])
            return {
                "status": "awaiting_human",
                "thread_id": thread_id,
                "interrupt": interrupt_value,
                "draft_reply": interrupt_value.get("draft_reply", "")
                if isinstance(interrupt_value, dict)
                else str(interrupt_value),
            }
        return {"status": "completed", "thread_id": thread_id, **result}

    def start_conversation(self, user_message: str, *, thread_id: str) -> dict[str, Any]:
        if not user_message.strip():
            raise ValueError("A conversation task must include at least one message.")

        result = self.graph.invoke(
            {"messages": [user_message]},
            config=self._config(thread_id),
        )
        return self._format_graph_result(result, thread_id)

    def resume_conversation(self, thread_id: str, decision: str) -> dict[str, Any]:
        result = self.graph.invoke(
            Command(resume=decision),
            config=self._config(thread_id),
        )
        return self._format_graph_result(result, thread_id)

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        messages = task_payload.get("messages", [])
        if not messages:
            raise ValueError("A conversation task must include at least one message.")

        draft_reply = f"I can help with: {messages[-1]}. Please confirm before I send the final answer."
        return {
            "messages": list(messages),
            "draft_reply": draft_reply,
            "approved": True,
            "final_reply": draft_reply,
        }

    def run_conversation(self, user_message: str) -> dict[str, Any]:
        return self.run_task({"messages": [user_message]})
