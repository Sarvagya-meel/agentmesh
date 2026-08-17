from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from threading import Event as ThreadEvent
from threading import Thread
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.control_plane_client import ControlPlaneClient
from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.agents.common.worker import AssignmentWorker
from agentmesh.config import Settings, get_settings

AgentFactory = Callable[[Settings], tuple[BaseAgent, Callable[[], None]]]


@runtime_checkable
class ResumableConversationAgent(Protocol):
    def start_conversation(self, user_message: str, *, thread_id: str) -> dict[str, Any]: ...

    def resume_conversation(self, thread_id: str, decision: str) -> dict[str, Any]: ...


class InvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    approval_required: bool = False
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1)


def worker_enabled_from_env() -> bool:
    """Return whether this runtime should poll the AgentMesh control plane."""

    return os.getenv("AGENT_WORKER_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def create_agent_runtime_app(
    *,
    kind: str,
    factory: AgentFactory,
    worker_enabled: bool = True,
) -> FastAPI:
    resolved_kind = kind.strip().lower()
    resolved_factory = factory

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = get_settings()
        service_agent, close_service_agent = resolved_factory(settings)
        app.state.agent = service_agent
        app.state.worker_thread = None
        app.state.worker_stop = None
        app.state.worker_client = None
        app.state.resource_repository = None

        def close_worker_agent() -> None:
            return None

        if worker_enabled:
            worker_agent, close_worker_agent = resolved_factory(settings)
            worker_client = ControlPlaneClient(
                settings.agentmesh_api_url,
                timeout_seconds=settings.worker_request_timeout_seconds,
            )
            resource_repository = PostgresResourceRepository.from_connection_url(
                settings.database_url
            )
            worker = AssignmentWorker(
                worker_agent,
                worker_client,
                poll_interval_seconds=settings.poll_interval_seconds,
                heartbeat_seconds=settings.worker_heartbeat_seconds,
                resource_repository=resource_repository,
            )
            worker_stop = ThreadEvent()
            worker_thread = Thread(
                target=worker.run_forever,
                kwargs={"stop_event": worker_stop},
                daemon=True,
                name=f"{worker_agent.agent_name}-assignment-worker",
            )
            app.state.worker_thread = worker_thread
            app.state.worker_stop = worker_stop
            app.state.worker_client = worker_client
            app.state.resource_repository = resource_repository
            worker_thread.start()

        try:
            yield
        finally:
            if app.state.worker_stop is not None:
                app.state.worker_stop.set()
            if app.state.worker_thread is not None:
                app.state.worker_thread.join(timeout=5)
            if app.state.resource_repository is not None:
                app.state.resource_repository.close()
            if app.state.worker_client is not None:
                app.state.worker_client.close()
            close_worker_agent()
            close_service_agent()

    app = FastAPI(title=f"AgentMesh {resolved_kind} agent", lifespan=lifespan)

    @app.get("/health", tags=["runtime"])
    async def health(request: Request) -> dict[str, str]:
        agent = _agent_from(request)
        return {"status": "ok", "agent_id": agent.agent_name}

    @app.get("/agent-card", tags=["runtime"])
    async def agent_card(request: Request) -> dict[str, Any]:
        return _agent_from(request).agent_card().model_dump(mode="json")

    @app.post("/invoke", tags=["runtime"])
    async def invoke(body: InvokeRequest, request: Request) -> dict[str, Any]:
        agent = _agent_from(request)
        if body.approval_required and isinstance(agent, ResumableConversationAgent):
            thread_id = body.thread_id or str(uuid4())
            return await run_in_threadpool(
                agent.start_conversation,
                body.message,
                thread_id=thread_id,
            )
        result = await run_in_threadpool(agent.run_task, {"messages": [body.message]})
        result.setdefault("status", "completed")
        return result

    @app.post("/conversations/{thread_id}/resume", tags=["runtime"])
    async def resume(
        thread_id: str,
        body: ResumeRequest,
        request: Request,
    ) -> dict[str, Any]:
        agent = _agent_from(request)
        if not isinstance(agent, ResumableConversationAgent):
            raise HTTPException(status_code=409, detail="This agent has no resumable conversation.")
        try:
            return await run_in_threadpool(agent.resume_conversation, thread_id, body.decision)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


def _agent_from(request: Request) -> BaseAgent:
    agent = getattr(request.app.state, "agent", None)
    if not isinstance(agent, BaseAgent):
        raise HTTPException(status_code=503, detail="Agent runtime is still starting.")
    return agent
