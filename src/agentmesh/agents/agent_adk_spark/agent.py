from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from threading import Event as ThreadEvent
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner as AdkRunner
from google.adk.sessions import BaseSessionService, DatabaseSessionService
from google.genai import types

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.core.models.exceptions import ModelProviderError
from agentmesh.core.observability import (
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
    resolve_trace_author,
    trace_author_metadata,
)


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
        session_service: BaseSessionService | None = None,
    ) -> None:
        self.model_name: str = model_name or os.getenv("GOOGLE_ADK_MODEL") or "gemini-2.5-flash"
        self._executor = executor
        self._session_service = session_service
        self._adk_runner: AdkRunner | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._event_thread: Thread | None = None
        self._runner_lock = Lock()
        if self._executor is None and api_key:
            if self._session_service is None:
                raise ValueError("A Google ADK session service is required for live execution.")
            self._adk_runner = self._build_adk_runner(
                api_key,
                self.model_name,
                self._session_service,
            )
            self._start_event_loop(agent_name)
        super().__init__(
            agent_name,
            auto_register=auto_register,
            endpoint=os.getenv("AGENT_ENDPOINT", "http://localhost:8002"),
            capabilities=["CHAT", "TRIP PLANNER", "GoogleADK"],
            skills=["google_adk", "conversation", "llm_connector"],
            description="Google ADK LLM worker for conversational and review tasks",
            owner="platform-team",
        )

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self._task_prompt(task_payload)
        user_id, session_id = self._session_identity(task_payload)
        nested_payload = task_payload.get("payload")
        nested = nested_payload if isinstance(nested_payload, dict) else {}
        workflow_id = str(task_payload.get("workflow_id") or nested.get("workflow_id") or "")
        task_id = str(task_payload.get("task_id") or nested.get("task_id") or "")
        mode = "WorkFlow" if workflow_id or task_id else "Direct"
        unique_id = workflow_id or session_id
        author = resolve_trace_author(self.agent_name, agent_card=self.agent_card())
        with agentmesh_span(
            agentmesh_run_name(mode, unique_id, prompt, author.author_name),
            inputs={"prompt": prompt},
            metadata=agentmesh_metadata(
                agent_id=self.agent_name,
                agent_name=author.author_name,
                execution_mode="workflow" if mode == "WorkFlow" else "direct",
                workflow_id=workflow_id,
                task_id=task_id,
                session_id=session_id,
                user_id=user_id,
                model=self.model_name,
                framework="google_adk",
                **trace_author_metadata(author),
            ),
            tags=["google-adk", self.agent_name],
        ) as run:
            if self._executor is not None:
                reply = self._executor(prompt)
            elif self._adk_runner is not None and self._event_loop is not None:
                with self._runner_lock:
                    reply = asyncio.run_coroutine_threadsafe(
                        self._execute_adk(prompt, user_id=user_id, session_id=session_id),
                        self._event_loop,
                    ).result()
            else:
                raise ModelProviderError(
                    "Google ADK has no configured model runtime. Set LLM_PROVIDER=groq, "
                    "provide GROQ_API_KEY, and configure a compatible GOOGLE_ADK_MODEL."
                )
            source = "google_adk_llm"
            response = {
                "status": "success",
                "agent": self.agent_name,
                "model": self.model_name,
                "final_reply": reply,
                "source": source,
                "session_id": session_id,
            }
            if run is not None:
                run.end(outputs={"status": response["status"], "source": source})
            return response

    def run_conversation(self, user_message: str) -> dict[str, Any]:
        return self.run_task({"messages": [user_message]})

    @staticmethod
    def _build_adk_runner(
        api_key: str,
        model_name: str,
        session_service: BaseSessionService,
    ) -> AdkRunner:
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
        return AdkRunner(
            agent=root_agent,
            app_name="agentmesh_adk_worker",
            session_service=session_service,
        )

    async def _execute_adk(self, prompt: str, *, user_id: str, session_id: str) -> str:
        if self._adk_runner is None or self._session_service is None:
            raise RuntimeError("Google ADK runtime is not configured.")
        session = await self._session_service.get_session(
            app_name="agentmesh_adk_worker",
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            await self._session_service.create_session(
                app_name="agentmesh_adk_worker",
                user_id=user_id,
                session_id=session_id,
            )
        final_text = ""
        async for event in self._adk_runner.run_async(
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

    def close(self) -> None:
        """Close the ADK database service and its dedicated asyncio loop."""

        if self._event_loop is None:
            return
        if isinstance(self._session_service, DatabaseSessionService):
            asyncio.run_coroutine_threadsafe(
                self._session_service.close(),
                self._event_loop,
            ).result()
        self._event_loop.call_soon_threadsafe(self._event_loop.stop)
        if self._event_thread is not None:
            self._event_thread.join(timeout=5)
        self._event_loop = None
        self._event_thread = None

    def _start_event_loop(self, agent_name: str) -> None:
        ready = ThreadEvent()
        loop = asyncio.new_event_loop()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()
            loop.close()

        thread = Thread(
            target=run_loop,
            daemon=True,
            name=f"{agent_name}-adk-event-loop",
        )
        thread.start()
        ready.wait(timeout=5)
        self._event_loop = loop
        self._event_thread = thread

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

    @staticmethod
    def _session_identity(task_payload: dict[str, Any]) -> tuple[str, str]:
        nested_payload = task_payload.get("payload")
        nested = nested_payload if isinstance(nested_payload, dict) else {}
        conversation_id = str(
            task_payload.get("conversation_id") or nested.get("conversation_id") or ""
        ).strip()
        user_id = str(
            task_payload.get("user_id")
            or nested.get("user_id")
            or conversation_id
            or "agentmesh-worker"
        )
        explicit_thread_id = str(
            task_payload.get("thread_id") or nested.get("thread_id") or ""
        ).strip()
        if explicit_thread_id:
            return user_id, explicit_thread_id
        workflow_id = str(task_payload.get("workflow_id") or nested.get("workflow_id") or "")
        task_id = str(task_payload.get("task_id") or nested.get("task_id") or "")
        if workflow_id and task_id:
            return user_id, f"agent:{workflow_id}:{task_id}"
        if conversation_id:
            return user_id, conversation_id
        return user_id, str(uuid4())
