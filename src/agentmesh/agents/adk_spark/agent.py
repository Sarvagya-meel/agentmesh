from __future__ import annotations

import os
from typing import Any

from agentmesh.agents.base import BaseAgent


class GoogleADKAgent(BaseAgent):
    """A lightweight, ADK-friendly adapter that works as a mockable local agent.

    This keeps the code compatible with the repo's event-driven architecture while
    providing a clear spot to plug in a real Google ADK implementation later.
    """

    def __init__(
        self,
        agent_name: str = "adk-spark",
        *,
        auto_register: bool = True,
        model_name: str | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("GOOGLE_ADK_MODEL", "gemini-2.0-flash")
        super().__init__(
            agent_name,
            auto_register=auto_register,
            endpoint=os.getenv("AGENT_ENDPOINT", "http://localhost:8002"),
            capabilities=["CHAT", "REVIEW", "ADK"],
            skills=["google_adk", "conversation"],
            description="Google ADK-compatible agent template for local orchestration testing",
            owner="platform-team",
        )

    def _build_adk_instruction(self, message: str) -> str:
        return (
            "You are a lightweight Google ADK-compatible agent. "
            f"The user request is: {message}. "
            "Return a concise structured response and mention that this is a local ADK-ready implementation."
        )

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        messages = task_payload.get("messages", [])
        if not isinstance(messages, list) or not messages:
            raise ValueError("A task payload for the Google ADK agent requires at least one message.")

        user_message = str(messages[-1])
        reply = self._build_adk_instruction(user_message)
        return {
            "status": "success",
            "agent": self.agent_name,
            "model": self.model_name,
            "final_reply": reply,
            "messages": messages,
            "source": "google_adk_adapter",
        }

    def run_conversation(self, user_message: str) -> dict[str, Any]:
        return self.run_task({"messages": [user_message]})
