from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from agentmesh.agents.agent_langgraph_orchestrator_supervisor.factory import create_workflow_planner
from agentmesh.agents.agent_langgraph_orchestrator_supervisor.planner import (
    CapabilityWorkflowPlanner,
    LLMWorkflowPlanner,
)
from agentmesh.core.config import Settings
from agentmesh.core.models.agent_card import AgentCard
from agentmesh.core.models.exceptions import (
    AgentRegistryError,
    ModelProviderError,
    ValidationError,
)
from agentmesh.core.providers.litellm import LiteLLMStructuredOutputClient


class FakeStructuredOutputClient:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.messages: list[dict[str, str]] = []
        self.schema: dict[str, Any] = {}

    def create_structured_output(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        request_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert schema_name == "agentmesh_workflow_plan"
        assert request_metadata is not None
        self.messages = messages
        self.schema = schema
        return self.output


def agent_cards() -> list[AgentCard]:
    return [
        AgentCard(
            agent_id="research-agent",
            name="Research Agent",
            capabilities=["RESEARCH"],
            skills=["web-search"],
        ),
        AgentCard(
            agent_id="review-agent",
            name="Review Agent",
            capabilities=["REVIEW"],
            skills=["quality-review"],
        ),
    ]


def test_litellm_planner_converts_strict_draft_to_agentmesh_plan() -> None:
    client = FakeStructuredOutputClient(
        {
            "rationale": "Research first, then review the findings.",
            "tasks": [
                {
                    "position": 0,
                    "name": "research_roles",
                    "description": "Research suitable roles.",
                    "required_capability": "RESEARCH",
                    "agent_id": "research-agent",
                    "dependency_positions": [],
                    "expected_output": "A ranked role list.",
                },
                {
                    "position": 1,
                    "name": "review_roles",
                    "description": "Review the ranked roles.",
                    "required_capability": "REVIEW",
                    "agent_id": "review-agent",
                    "dependency_positions": [0],
                    "expected_output": "An approved shortlist.",
                },
            ],
        }
    )
    planner = LLMWorkflowPlanner(client, model_name="agentmesh-groq")

    plan = planner.create_plan(
        workflow_id=uuid4(),
        goal="Research suitable roles and review them",
        agents=agent_cards(),
        preferred_agent_ids=["research-agent", "review-agent"],
    )

    assert [task.agent_id for task in plan.tasks] == ["research-agent", "review-agent"]
    assert plan.tasks[1].dependencies == [plan.tasks[0].task_id]
    assert plan.tasks[0].payload["goal"] == "Research suitable roles and review them"
    assert plan.planner_provider == "litellm"
    assert plan.planner_model == "agentmesh-groq"
    assert client.schema["additionalProperties"] is False
    assert set(json.loads(client.messages[1]["content"])["available_agents"][0]) == {
        "agent_id",
        "name",
        "description",
        "capabilities",
        "skills",
    }


def test_litellm_planner_rejects_unadvertised_capability() -> None:
    client = FakeStructuredOutputClient(
        {
            "rationale": "Use an invalid capability.",
            "tasks": [
                {
                    "position": 0,
                    "name": "send_email",
                    "description": "Send an email.",
                    "required_capability": "EMAIL",
                    "agent_id": "research-agent",
                    "dependency_positions": [],
                    "expected_output": "A sent email.",
                }
            ],
        }
    )

    with pytest.raises(AgentRegistryError, match="does not advertise"):
        LLMWorkflowPlanner(client).create_plan(
            workflow_id=uuid4(),
            goal="Send an email",
            agents=agent_cards(),
            preferred_agent_ids=["research-agent"],
        )


def test_litellm_client_requests_strict_json_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["model"] == "agentmesh-groq"
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"rationale": "ok", "tasks": []})}}]
            },
        )

    client = LiteLLMStructuredOutputClient(
        api_key="test-key",
        model="agentmesh-groq",
        api_base="http://litellm:4000/v1",
        reasoning_effort="medium",
        temperature=0.1,
        max_completion_tokens=4096,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
        retry_attempts=1,
    )
    try:
        result = client.create_structured_output(
            messages=[{"role": "user", "content": "plan"}],
            schema_name="plan",
            schema={"type": "object", "additionalProperties": False},
        )
    finally:
        client.close()

    assert result["rationale"] == "ok"


def test_planner_factory_requires_gateway_key_for_litellm() -> None:
    settings = Settings(_env_file=None, llm_provider="litellm", litellm_master_key="")

    with pytest.raises(ValidationError, match="LITELLM_MASTER_KEY"):
        create_workflow_planner(settings)


def test_planner_factory_uses_litellm_gateway_alias() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="litellm",
        litellm_master_key="gateway-key",
        litellm_api_base="http://litellm:4000/v1",
        litellm_model="agentmesh-groq",
    )

    planner, close = create_workflow_planner(settings)
    try:
        assert isinstance(planner, LLMWorkflowPlanner)
        assert planner.model_name == "agentmesh-groq"
    finally:
        close()


def test_planner_factory_keeps_mock_mode_offline() -> None:
    settings = Settings(_env_file=None, llm_provider="mock")

    planner, close = create_workflow_planner(settings)
    close()

    assert isinstance(planner, CapabilityWorkflowPlanner)


def test_litellm_client_maps_rate_limits_to_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "3"}, json={"error": "limited"})

    client = LiteLLMStructuredOutputClient(
        api_key="test-key",
        model="agentmesh-groq",
        api_base="http://litellm:4000/v1",
        reasoning_effort="medium",
        temperature=0.1,
        max_completion_tokens=4096,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ModelProviderError, match="Retry after 3") as captured:
            client.create_structured_output(
                messages=[{"role": "user", "content": "plan"}],
                schema_name="plan",
                schema={"type": "object", "additionalProperties": False},
            )
    finally:
        client.close()

    assert captured.value.retryable is True
    assert captured.value.status_code == 429
    assert captured.value.retry_after_seconds == 3.0


def test_litellm_client_retries_a_rate_limit() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "recovered"}}]},
        )

    client = LiteLLMStructuredOutputClient(
        api_key="test-key",
        model="agentmesh-groq",
        api_base="http://litellm:4000/v1",
        reasoning_effort="",
        temperature=0.1,
        max_completion_tokens=100,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.create_text_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        client.close()

    assert result == "recovered"
    assert calls == 2
