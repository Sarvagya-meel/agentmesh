import asyncio
from typing import Any

from agentmesh.agents.common.base_agent import BaseAgent
from agentmesh.agents.common.execution import AgentExecutor, ExecutionContext


class AsyncProbeAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("probe", auto_register=False)
        self.active = 0
        self.max_active = 0

    def run_task(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        return task_payload

    async def arun_task(
        self,
        task_payload: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        del context
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.03)
        self.active -= 1
        return task_payload


async def test_executor_serializes_the_same_thread() -> None:
    agent = AsyncProbeAgent()
    executor = AgentExecutor(agent, max_concurrency=4)

    await asyncio.gather(
        executor.execute({"value": 1}, ExecutionContext("test", thread_id="same")),
        executor.execute({"value": 2}, ExecutionContext("test", thread_id="same")),
    )

    assert agent.max_active == 1


async def test_executor_runs_different_threads_concurrently() -> None:
    agent = AsyncProbeAgent()
    executor = AgentExecutor(agent, max_concurrency=2)

    await asyncio.gather(
        executor.execute({"value": 1}, ExecutionContext("test", thread_id="one")),
        executor.execute({"value": 2}, ExecutionContext("test", thread_id="two")),
    )

    assert agent.max_active == 2


async def test_executor_drain_rejects_new_work_and_waits_for_active_work() -> None:
    agent = AsyncProbeAgent()
    executor = AgentExecutor(agent, max_concurrency=1)
    active = asyncio.create_task(
        executor.execute({"value": 1}, ExecutionContext("test", thread_id="one"))
    )
    await asyncio.sleep(0)

    drained = await executor.drain(timeout_seconds=1)
    await active

    assert drained is True
    try:
        await executor.execute({"value": 2}, ExecutionContext("test"))
    except RuntimeError as exc:
        assert "draining" in str(exc)
    else:
        raise AssertionError("Draining executor accepted new work.")
