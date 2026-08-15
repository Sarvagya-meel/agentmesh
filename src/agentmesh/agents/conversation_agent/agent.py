from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from agentmesh.agents.base import BaseAgent


class ConversationAgent(BaseAgent):
    """A small LangGraph-based conversation agent with a human approval checkpoint."""

    def __init__(self, agent_name: str = "conversation_agent") -> None:
        super().__init__(agent_name)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(dict)

        def draft_response(state: dict[str, Any]) -> dict[str, Any]:
            last_message = state.get("messages", [])[-1] if state.get("messages") else ""
            reply = f"I can help with: {last_message}. Please confirm before I send the final answer."
            return {"draft_reply": reply}

        def human_approval(state: dict[str, Any]) -> dict[str, Any]:
            approval = interrupt({
                "type": "human_approval",
                "prompt": "Review the draft response before sending it.",
                "draft_reply": state.get("draft_reply", ""),
            })
            decision = str(approval).strip().lower()
            return {"approved": decision in {"approve", "approved", "yes"}, "final_reply": state.get("draft_reply", "")}

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
        return graph.compile()

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
