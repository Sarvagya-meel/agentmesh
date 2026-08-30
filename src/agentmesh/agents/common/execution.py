from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.core.observability import agentmesh_metadata, agentmesh_run_name, agentmesh_span


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Runtime metadata that is independent from an agent framework."""

    source: str
    thread_id: str | None = None
    workflow_id: str | None = None
    assignment_id: str | None = None
    attempt_number: int = 1
    run_id: str = field(default_factory=lambda: str(uuid4()))


class AgentExecutor:
    """Bound concurrency and serialize executions that share a thread ID."""

    def __init__(self, agent: BaseAgent, *, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one.")
        self.agent = agent
        self._capacity = asyncio.Semaphore(max_concurrency)
        self._thread_locks: dict[str, asyncio.Lock] = {}
        self._thread_lock_guard = asyncio.Lock()
        self._active_condition = asyncio.Condition()
        self._active_count = 0
        self._draining = False

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def draining(self) -> bool:
        return self._draining

    async def execute(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        if self._draining:
            raise RuntimeError("Agent runtime is draining and cannot accept new work.")

        thread_lock = await self._lock_for(context.thread_id)
        async with self._capacity:
            if thread_lock is None:
                return await self._execute(payload, context)
            async with thread_lock:
                return await self._execute(payload, context)

    async def drain(self, *, timeout_seconds: float = 30.0) -> bool:
        self._draining = True

        async def wait_until_idle() -> None:
            async with self._active_condition:
                await self._active_condition.wait_for(lambda: self._active_count == 0)

        try:
            await asyncio.wait_for(wait_until_idle(), timeout=timeout_seconds)
        except TimeoutError:
            return False
        return True

    async def _execute(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        async with self._active_condition:
            self._active_count += 1
        try:
            task_id = payload.get("task_id")
            execution_mode = "workflow" if context.source == "assignment" else context.source
            with agentmesh_span(
                agentmesh_run_name(
                    "WorkFlow" if execution_mode == "workflow" else "Direct",
                    context.workflow_id or context.thread_id or context.run_id,
                    str(payload.get("description") or payload.get("messages") or "agent execution"),
                    self.agent.agent_name,
                ),
                inputs={"payload_keys": sorted(payload)},
                metadata=agentmesh_metadata(
                    agent_id=self.agent.agent_name,
                    execution_mode=execution_mode,
                    source=context.source,
                    workflow_id=context.workflow_id,
                    assignment_event_id=context.assignment_id,
                    assignment_id=context.assignment_id,
                    task_id=task_id,
                    thread_id=context.thread_id,
                    attempt_number=context.attempt_number,
                    run_id=context.run_id,
                ),
                tags=["agent-execution", self.agent.agent_name],
            ) as run:
                result = await self.agent.arun_task(payload, context)
                if run is not None:
                    run.end(outputs={"status": result.get("status"), "result_keys": sorted(result)})
                return result
        finally:
            async with self._active_condition:
                self._active_count -= 1
                self._active_condition.notify_all()

    async def _lock_for(self, thread_id: str | None) -> asyncio.Lock | None:
        if not thread_id:
            return None
        async with self._thread_lock_guard:
            return self._thread_locks.setdefault(thread_id, asyncio.Lock())
