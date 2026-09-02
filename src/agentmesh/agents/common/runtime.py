from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.control_plane_client import AsyncControlPlaneClient
from agentmesh.agents.common.execution import AgentExecutor, ExecutionContext
from agentmesh.agents.common.resource_repository import PostgresResourceRepository
from agentmesh.agents.common.worker import AssignmentWorker
from agentmesh.config import Settings, get_settings
from agentmesh.core.models.exceptions import ModelProviderError
from agentmesh.core.observability import (
    agentmesh_metadata,
    agentmesh_run_name,
    agentmesh_span,
    configure_langsmith,
    resolve_trace_author,
    trace_author_metadata,
)

Cleanup = Callable[[], None | Awaitable[None]]
FactoryResult = tuple[BaseAgent, Cleanup]
AgentFactory = Callable[[Settings], FactoryResult | Awaitable[FactoryResult]]
RUNTIME_ROLES = {"combined", "api", "worker"}


class InvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    approval_required: bool = False
    thread_id: str | None = None
    user_id: str | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1)
    feedback: str = ""


class CheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)


class ForkCheckpointRequest(CheckpointRequest):
    new_thread_id: str = Field(min_length=1)
    state_updates: dict[str, Any] = Field(default_factory=dict)


def runtime_role_from_env() -> str:
    """Read and validate the process role once while constructing the app."""

    role = os.getenv("AGENT_RUNTIME_ROLE", "combined").strip().lower()
    if role not in RUNTIME_ROLES:
        choices = ", ".join(sorted(RUNTIME_ROLES))
        raise ValueError(f"AGENT_RUNTIME_ROLE must be one of: {choices}.")
    return role


def worker_enabled_from_env() -> bool:
    """Compatibility helper for older launchers; roles are authoritative."""

    legacy = os.getenv("AGENT_WORKER_ENABLED")
    if legacy is not None:
        return legacy.strip().lower() in {"1", "true", "yes"}
    return runtime_role_from_env() in {"combined", "worker"}


def create_agent_runtime_app(
    *,
    kind: str,
    factory: AgentFactory,
    runtime_role: str | None = None,
    worker_enabled: bool | None = None,
) -> FastAPI:
    """Create one process runtime around exactly one initialized agent executor."""

    resolved_kind = kind.strip().lower()
    resolved_factory = factory
    resolved_role = (runtime_role or runtime_role_from_env()).strip().lower()
    if resolved_role not in RUNTIME_ROLES:
        raise ValueError(f"Unsupported agent runtime role {resolved_role!r}.")
    presence_enabled = worker_enabled is not False
    if worker_enabled is False and runtime_role is None:
        resolved_role = "api"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = get_settings()
        configure_langsmith(settings)
        factory_result = resolved_factory(settings)
        if inspect.isawaitable(factory_result):
            factory_result = await factory_result
        agent, close_agent = factory_result
        executor = AgentExecutor(agent, max_concurrency=settings.agent_max_concurrency)
        app.state.agent = agent
        app.state.executor = executor
        app.state.runtime_role = resolved_role
        app.state.presence = None
        app.state.runtime_task = None
        app.state.runtime_stop = None
        app.state.worker_client = None
        app.state.resource_repository = None

        if presence_enabled:
            client = AsyncControlPlaneClient(
                settings.agentmesh_api_url,
                timeout_seconds=settings.worker_request_timeout_seconds,
            )
            resource_repository = PostgresResourceRepository.from_connection_url(
                settings.database_url
            )
            presence = AssignmentWorker(
                executor,
                client,
                runtime_role=resolved_role,
                poll_interval_seconds=settings.poll_interval_seconds,
                heartbeat_seconds=settings.worker_heartbeat_seconds,
                resource_repository=resource_repository,
                max_concurrency=settings.agent_max_concurrency,
            )
            stop_event = asyncio.Event()
            app.state.presence = presence
            app.state.runtime_stop = stop_event
            app.state.worker_client = client
            app.state.resource_repository = resource_repository
            try:
                await presence.start()
            except (httpx.HTTPError, OSError):
                presence.runtime_status = "DEGRADED"
            app.state.runtime_task = asyncio.create_task(
                presence.run_forever(
                    stop_event,
                    consume_assignments=resolved_role in {"combined", "worker"},
                ),
                name=f"{agent.agent_name}-{resolved_role}-runtime",
            )

        try:
            yield
        finally:
            if app.state.presence is not None:
                await app.state.presence._set_runtime_status(
                    "DRAINING", "Agent runtime is draining during shutdown."
                )
            await executor.drain(timeout_seconds=settings.agent_shutdown_timeout_seconds)
            if app.state.runtime_stop is not None:
                app.state.runtime_stop.set()
            if app.state.runtime_task is not None:
                await app.state.runtime_task
            if app.state.presence is not None:
                await app.state.presence.stop()
            if app.state.resource_repository is not None:
                await asyncio.to_thread(app.state.resource_repository.close)
            if app.state.worker_client is not None:
                await app.state.worker_client.close()
            cleanup_result = close_agent()
            if inspect.isawaitable(cleanup_result):
                await cleanup_result

    app = FastAPI(title=f"AgentMesh {resolved_kind} agent", lifespan=lifespan)

    @app.get("/health", tags=["runtime"])
    async def health(request: Request) -> dict[str, Any]:
        agent = _agent_from(request)
        return {
            "status": "ok",
            "agent_id": agent.agent_name,
            "runtime_role": resolved_role,
        }

    @app.get("/ready", tags=["runtime"])
    async def ready(request: Request) -> JSONResponse:
        presence = getattr(request.app.state, "presence", None)
        if not presence_enabled:
            return JSONResponse(
                {
                    "status": "ready",
                    "runtime_role": resolved_role,
                    "presence_enabled": False,
                }
            )
        is_ready = isinstance(presence, AssignmentWorker) and presence.ready
        return JSONResponse(
            {
                "status": "ready" if is_ready else "not_ready",
                "runtime_role": resolved_role,
                "presence_enabled": True,
                "runtime_status": getattr(presence, "runtime_status", "STARTING"),
                "runtime_instance_id": getattr(presence, "runtime_instance_id", None),
                "active_execution_count": _executor_from(request).active_count,
            },
            status_code=200 if is_ready else 503,
        )

    if resolved_role in {"combined", "api"}:

        @app.get("/agent-card", tags=["runtime"])
        async def agent_card(request: Request) -> dict[str, Any]:
            return _agent_from(request).agent_card().model_dump(mode="json")

        @app.post("/invoke", tags=["runtime"])
        async def invoke(body: InvokeRequest, request: Request) -> dict[str, Any]:
            presence = getattr(request.app.state, "presence", None)
            if presence_enabled and not (isinstance(presence, AssignmentWorker) and presence.ready):
                raise HTTPException(status_code=503, detail="Agent runtime is not ready.")
            thread_id = body.thread_id or str(uuid4())
            payload: dict[str, Any] = {
                "messages": [body.message],
                "approval_required": body.approval_required,
                "thread_id": thread_id,
            }
            if body.user_id:
                payload["user_id"] = body.user_id
            try:
                agent = _agent_from(request)
                agent_card = agent.agent_card()
                author = resolve_trace_author(
                    body.user_id or agent.agent_name,
                    agent_card=None if body.user_id else agent_card,
                    author_type="user" if body.user_id else None,
                )
                with agentmesh_span(
                    agentmesh_run_name(
                        "Direct",
                        thread_id,
                        body.message,
                        author.author_name,
                    ),
                    inputs={"message_present": True, "approval_required": body.approval_required},
                    metadata=agentmesh_metadata(
                        agent_id=agent.agent_name,
                        agent_name=agent_card.name,
                        execution_mode="direct",
                        source="direct",
                        thread_id=thread_id,
                        user_id=body.user_id,
                        **trace_author_metadata(author),
                    ),
                    tags=["direct", agent.agent_name],
                ) as run:
                    result = await _executor_from(request).execute(
                        payload,
                        ExecutionContext(source="direct", thread_id=thread_id),
                    )
                    if run is not None:
                        run.end(outputs={"status": result.get("status"), "thread_id": thread_id})
            except (ModelProviderError, RuntimeError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            result.setdefault("status", "completed")
            return result

        @app.post("/conversations/{thread_id}/resume", tags=["runtime"])
        async def resume(
            thread_id: str,
            body: ResumeRequest,
            request: Request,
        ) -> dict[str, Any]:
            try:
                agent = _agent_from(request)
                author = resolve_trace_author(agent.agent_name, agent_card=agent.agent_card())
                with agentmesh_span(
                    agentmesh_run_name(
                        "Direct",
                        thread_id,
                        f"resume approval {body.decision}",
                        author.author_name,
                    ),
                    inputs={"decision": body.decision, "feedback_present": bool(body.feedback)},
                    metadata=agentmesh_metadata(
                        agent_id=agent.agent_name,
                        agent_name=author.author_name,
                        execution_mode="direct_resume",
                        source="direct_resume",
                        thread_id=thread_id,
                        **trace_author_metadata(author),
                    ),
                    tags=["direct", "resume", agent.agent_name],
                ) as run:
                    result = await _executor_from(request).execute(
                        {
                            "resume_thread_id": thread_id,
                            "approval_decision": body.decision,
                            "approval_feedback": body.feedback,
                        },
                        ExecutionContext(source="direct_resume", thread_id=thread_id),
                    )
                    if run is not None:
                        run.end(outputs={"status": result.get("status"), "thread_id": thread_id})
                    return result
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except (ModelProviderError, RuntimeError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        @app.get("/conversations/{thread_id}/checkpoints", tags=["langgraph"])
        async def checkpoints(thread_id: str, request: Request) -> list[dict[str, Any]]:
            agent = cast(Any, _agent_from(request))
            method = getattr(agent, "checkpoint_history", None)
            if method is None:
                raise HTTPException(status_code=404, detail="Checkpoint history is unavailable.")
            author = resolve_trace_author(agent.agent_name, agent_card=agent.agent_card())
            with agentmesh_span(
                agentmesh_run_name(
                    "Direct",
                    thread_id,
                    "checkpoint history",
                    author.author_name,
                ),
                inputs={"thread_id": thread_id},
                metadata=agentmesh_metadata(
                    agent_id=agent.agent_name,
                    agent_name=author.author_name,
                    execution_mode="checkpoint_api",
                    thread_id=thread_id,
                    checkpoint_operation="history",
                    **trace_author_metadata(author),
                ),
                tags=["checkpoint", agent.agent_name],
            ) as run:
                history = cast(list[dict[str, Any]], await method(thread_id))
                if run is not None:
                    run.end(outputs={"checkpoint_count": len(history)})
                return history

        @app.post("/conversations/{thread_id}/replay", tags=["langgraph"])
        async def replay_checkpoint(
            thread_id: str,
            body: CheckpointRequest,
            request: Request,
        ) -> dict[str, Any]:
            agent = cast(Any, _agent_from(request))
            method = getattr(agent, "replay_checkpoint", None)
            if method is None:
                raise HTTPException(status_code=404, detail="Checkpoint replay is unavailable.")
            author = resolve_trace_author(agent.agent_name, agent_card=agent.agent_card())
            with agentmesh_span(
                agentmesh_run_name(
                    "Direct",
                    thread_id,
                    f"checkpoint replay {body.checkpoint_id}",
                    author.author_name,
                ),
                inputs={"thread_id": thread_id, "checkpoint_id": body.checkpoint_id},
                metadata=agentmesh_metadata(
                    agent_id=agent.agent_name,
                    agent_name=author.author_name,
                    execution_mode="checkpoint_api",
                    thread_id=thread_id,
                    checkpoint_id=body.checkpoint_id,
                    checkpoint_operation="replay",
                    **trace_author_metadata(author),
                ),
                tags=["checkpoint", "replay", agent.agent_name],
            ) as run:
                result = cast(dict[str, Any], await method(thread_id, body.checkpoint_id))
                if run is not None:
                    run.end(outputs={"result_keys": sorted(result)})
                return result

        @app.post("/conversations/{thread_id}/fork", tags=["langgraph"])
        async def fork_checkpoint(
            thread_id: str,
            body: ForkCheckpointRequest,
            request: Request,
        ) -> dict[str, Any]:
            agent = cast(Any, _agent_from(request))
            method = getattr(agent, "fork_checkpoint", None)
            if method is None:
                raise HTTPException(status_code=404, detail="Checkpoint fork is unavailable.")
            author = resolve_trace_author(agent.agent_name, agent_card=agent.agent_card())
            with agentmesh_span(
                agentmesh_run_name(
                    "Direct",
                    thread_id,
                    f"checkpoint fork {body.checkpoint_id}",
                    author.author_name,
                ),
                inputs={
                    "thread_id": thread_id,
                    "checkpoint_id": body.checkpoint_id,
                    "new_thread_id": body.new_thread_id,
                    "state_update_keys": sorted(body.state_updates),
                },
                metadata=agentmesh_metadata(
                    agent_id=agent.agent_name,
                    agent_name=author.author_name,
                    execution_mode="checkpoint_api",
                    thread_id=thread_id,
                    checkpoint_id=body.checkpoint_id,
                    checkpoint_operation="fork",
                    new_thread_id=body.new_thread_id,
                    **trace_author_metadata(author),
                ),
                tags=["checkpoint", "fork", agent.agent_name],
            ) as run:
                result = cast(
                    dict[str, Any],
                    await method(
                        thread_id,
                        body.checkpoint_id,
                        new_thread_id=body.new_thread_id,
                        state_updates=body.state_updates,
                    ),
                )
                if run is not None:
                    run.end(outputs={"checkpoint_id": result.get("checkpoint_id")})
                return result

        @app.get("/graph/mermaid", tags=["langgraph"], response_class=PlainTextResponse)
        async def graph_mermaid(request: Request) -> str:
            agent = cast(Any, _agent_from(request))
            method = getattr(agent, "graph_mermaid", None)
            if method is None:
                raise HTTPException(status_code=404, detail="Graph visualization is unavailable.")
            return str(method())

    return app


def _agent_from(request: Request) -> BaseAgent:
    agent = getattr(request.app.state, "agent", None)
    if not isinstance(agent, BaseAgent):
        raise HTTPException(status_code=503, detail="Agent runtime is still starting.")
    return agent


def _executor_from(request: Request) -> AgentExecutor:
    executor = getattr(request.app.state, "executor", None)
    if not isinstance(executor, AgentExecutor):
        raise HTTPException(status_code=503, detail="Agent runtime is still starting.")
    return executor
