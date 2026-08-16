from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from agentmesh.agents.common.agent_models import BaseAgent


class GoogleADKAgent(BaseAgent):
    """Google ADK worker backed by a real LlmAgent when credentials are injected."""

    def __init__(
        self,
        agent_name: str = "googleADK-Chatagent",
        *,
        auto_register: bool = True,
        model_name: str | None = None,
        api_key: str | None = None,
        executor: Callable[[str], str] | None = None,
    ) -> None:
        self.model_name: str = (
            model_name or os.getenv("GOOGLE_ADK_MODEL") or "gemini-2.5-flash"
        )
        self._executor = executor
        if self._executor is None and api_key:
            self._executor = self._build_adk_executor(api_key, self.model_name)
        super().__init__(
            agent_name,
            auto_register=auto_register,
            endpoint=os.getenv("AGENT_ENDPOINT", "http://localhost:8002"),
            capabilities=["CHAT", "REVIEW", "ADK"],
            skills=["google_adk", "conversation", "llm_connector"],
            description="Google ADK LLM worker for conversational and review tasks",
            owner="platform-team",
        )

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self._task_prompt(task_payload)
        reply = (
            self._executor(prompt)
            if self._executor is not None
            else f"Local ADK fallback response for: {prompt}"
        )
        return {
            "status": "success",
            "agent": self.agent_name,
            "model": self.model_name,
            "final_reply": reply,
            "source": "google_adk_llm" if self._executor is not None else "local_fallback",
        }

    def run_conversation(self, user_message: str) -> dict[str, Any]:
        return self.run_task({"messages": [user_message]})

    @staticmethod
    def _build_adk_executor(api_key: str, model_name: str) -> Callable[[str], str]:
        os.environ["GROQ_API_KEY"] = api_key
        os.environ.setdefault("PYTHONUTF8", "1")
        provider_model = model_name if model_name.startswith("groq/") else f"groq/{model_name}"
        root_agent = LlmAgent(
            name="adk_spark_worker",
            model=LiteLlm(model=provider_model, include_reasoning=False),
            description="AgentMesh Google ADK worker",
            instruction=(
                "Complete the assigned AgentMesh task concisely. Return only useful task output, "
                "and do not claim actions you did not perform."
            ),
        )
        runner = InMemoryRunner(agent=root_agent, app_name="agentmesh_adk_worker")

        async def execute_async(prompt: str) -> str:
            user_id = "agentmesh-worker"
            session_id = str(uuid4())
            await runner.session_service.create_session(
                app_name="agentmesh_adk_worker",
                user_id=user_id,
                session_id=session_id,
            )
            final_text = ""
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                ),
            ):
                if event.is_final_response() and event.content is not None:
                    final_text = "".join(
                        part.text or "" for part in event.content.parts or [] if part.text
                    ).strip()
            if not final_text:
                raise RuntimeError("Google ADK returned no final text response.")
            return final_text

        return lambda prompt: asyncio.run(execute_async(prompt))

    @staticmethod
    def _task_prompt(task_payload: dict[str, Any]) -> str:
        messages = task_payload.get("messages")
        if isinstance(messages, list) and messages:
            return str(messages[-1])
        nested_payload = task_payload.get("payload")
        goal = str(nested_payload.get("goal", "")) if isinstance(nested_payload, dict) else ""
        description = str(task_payload.get("description", "")).strip()
        prompt = "\n\n".join(part for part in [description, goal] if part)
        if not prompt:
            raise ValueError("A Google ADK task requires messages, a goal, or a description.")
        return prompt
