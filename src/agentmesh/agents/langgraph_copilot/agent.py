from __future__ import annotations

import os
from typing import Any, Protocol, TypedDict, cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentmesh.agents.base import BaseAgent


class ConversationState(TypedDict, total=False):
    messages: list[str]
    draft_reply: str
    approved: bool
    final_reply: str
    human_decision: str
    pending_human_input: dict[str, Any]
    approval_required: bool


class TextCompletionClient(Protocol):
    """Minimal text generation contract injected into the LangGraph worker."""

    model: str

    def create_text_completion(self, *, messages: list[dict[str, str]]) -> str:
        """Generate one assistant response."""


class ConversationAgent(BaseAgent):
    """A small LangGraph-based conversation agent with a human approval checkpoint."""

    def __init__(
        self,
        agent_name: str = "langgraph-copilot",
        *,
        auto_register: bool = True,
        llm_client: TextCompletionClient | None = None,
    ) -> None:
        self.llm_client = llm_client
        super().__init__(
            agent_name,
            auto_register=auto_register,
            endpoint=os.getenv("AGENT_ENDPOINT", "http://localhost:8001"),
            capabilities=["CHAT", "REVIEW"],
            skills=["conversation", "human_approval"],
            description="Conversation agent with human-in-the-loop approval",
        )
        self.llm_model = (
            llm_client.model
            if llm_client is not None
            else os.getenv("LANGGRAPH_MODEL", "local-langgraph-agent")
        )
        self.graph = self._build_graph()
        self.pending_threads: dict[str, ConversationState] = {}

    def _build_graph(
        self,
    ) -> CompiledStateGraph[ConversationState, None, ConversationState, ConversationState]:
        graph = StateGraph(ConversationState)

        def draft_response(state: ConversationState) -> ConversationState:
            if state.get("draft_reply"):
                return {"draft_reply": state["draft_reply"]}
            last_message = state.get("messages", [])[-1] if state.get("messages") else ""
            reply = self._generate_reply(last_message)
            return {"draft_reply": reply}

        def human_approval(state: ConversationState) -> ConversationState:
            draft_reply = state.get("draft_reply", "")
            if not state.get("approval_required", True):
                return {"approved": True, "draft_reply": draft_reply}
            decision = str(state.get("human_decision", "")).strip().lower()
            if not decision:
                return {
                    "draft_reply": draft_reply,
                    "pending_human_input": {
                        "type": "human_approval",
                        "prompt": "Review the draft response before sending it.",
                        "draft_reply": draft_reply,
                        "options": ["approve", "reject"],
                    },
                }
            return {
                "approved": decision in {"approve", "approved", "yes"},
                "draft_reply": draft_reply,
            }

        def finalize(state: ConversationState) -> ConversationState:
            if state.get("approved"):
                return {"final_reply": state.get("draft_reply", "")}
            return {"final_reply": "I paused the response and am waiting for your approval."}

        graph.add_node("draft_response", draft_response)
        graph.add_node("human_approval", human_approval)
        graph.add_node("finalize", finalize)
        graph.set_entry_point("draft_response")
        graph.add_edge("draft_response", "human_approval")
        graph.add_edge("human_approval", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _format_graph_result(self, result: dict[str, Any], thread_id: str) -> dict[str, Any]:
        if result.get("pending_human_input"):
            interrupt_value = result["pending_human_input"]
            return {
                "status": "awaiting_human",
                "thread_id": thread_id,
                "interrupt": interrupt_value,
                "draft_reply": interrupt_value.get("draft_reply", ""),
                "prompt": interrupt_value.get(
                    "prompt", "Review the draft response before sending it."
                ),
                "options": interrupt_value.get("options", ["approve", "reject"]),
                "llm_model": self.llm_model,
            }
        return {
            "status": "completed",
            "thread_id": thread_id,
            "llm_model": self.llm_model,
            **result,
        }

    def start_conversation(self, user_message: str, *, thread_id: str) -> dict[str, Any]:
        if not user_message.strip():
            raise ValueError("A conversation task must include at least one message.")

        state = ConversationState(messages=[user_message], approval_required=True)
        result = self.graph.invoke(state)
        self.pending_threads[thread_id] = cast(ConversationState, dict(result))
        self.pending_threads[thread_id]["messages"] = [user_message]
        return self._format_graph_result(dict(result), thread_id)

    def resume_conversation(self, thread_id: str, decision: str) -> dict[str, Any]:
        state = self.pending_threads.get(thread_id)
        if state is None:
            raise ValueError(f"No pending conversation for thread {thread_id!r}.")

        resume_state = ConversationState(
            messages=state.get("messages", []),
            draft_reply=state.get("draft_reply", ""),
            human_decision=decision,
            approval_required=True,
        )
        result = self.graph.invoke(resume_state)
        self.pending_threads.pop(thread_id, None)
        return self._format_graph_result(dict(result), thread_id)

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self._task_prompt(task_payload)
        result = self.graph.invoke(
            ConversationState(messages=[prompt], approval_required=False)
        )
        return {"agent": self.agent_name, "model": self.llm_model, **dict(result)}

    def run_conversation(self, user_message: str) -> dict[str, Any]:
        return self.run_task({"messages": [user_message]})

    def _generate_reply(self, prompt: str) -> str:
        if self.llm_client is None:
            return f"I can help with: {prompt}. This is the local LangGraph response."
        return self.llm_client.create_text_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the LangGraph worker in AgentMesh. Complete the assigned task "
                        "concisely, return only useful task output, and do not claim actions that "
                        "you did not perform."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )

    @staticmethod
    def _task_prompt(task_payload: dict[str, Any]) -> str:
        messages = task_payload.get("messages")
        if isinstance(messages, list) and messages:
            return str(messages[-1])
        goal = str(task_payload.get("payload", {}).get("goal", ""))
        description = str(task_payload.get("description", "")).strip()
        prompt = "\n\n".join(part for part in [description, goal] if part)
        if not prompt:
            raise ValueError("A LangGraph task requires messages, a goal, or a description.")
        return prompt
