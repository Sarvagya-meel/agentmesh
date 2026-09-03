from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DATASET_NAME = "AgentMesh Sanity Eval"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def score_workflow_consistency(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    expected_agents = set(reference_outputs.get("expected_agents", []))
    planned_agents = set(outputs.get("planned_agents", []))
    final_status_ok = outputs.get("status") == reference_outputs.get("status", "COMPLETED")
    score = float(expected_agents.issubset(planned_agents) and final_status_ok)
    return {
        "key": "workflow_consistency",
        "score": score,
        "comment": f"planned_agents={sorted(planned_agents)} status={outputs.get('status')}",
    }


def score_approval_gate(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    events = outputs.get("event_types", [])
    required = reference_outputs.get(
        "required_events",
        ["PLAN_APPROVAL_REQUESTED", "PLAN_APPROVED", "AGENT_APPROVAL_REQUESTED"],
    )
    missing = [event for event in required if event not in events]
    return {
        "key": "approval_gate_events",
        "score": 0.0 if missing else 1.0,
        "comment": f"missing={missing}",
    }


def score_routing_choice(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    expected = set(reference_outputs.get("expected_agents", []))
    assigned = set(outputs.get("assigned_agents", []))
    score = len(expected & assigned) / max(len(expected), 1)
    return {
        "key": "routing_choice",
        "score": score,
        "comment": f"assigned_agents={sorted(assigned)} expected={sorted(expected)}",
    }


def score_final_answer_faithfulness(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    previous = str(outputs.get("previous_task_output", "")).lower()
    final = str(outputs.get("final_answer", "")).lower()
    important_terms = [term for term in reference_outputs.get("must_preserve_terms", []) if term]
    if important_terms:
        missing = [term for term in important_terms if str(term).lower() not in final]
        score = 0.0 if missing else 1.0
        comment = f"missing_terms={missing}"
    else:
        previous_tokens = {token for token in previous.split() if len(token) > 3}
        overlap = previous_tokens & set(final.split())
        score = min(len(overlap) / max(len(previous_tokens), 1), 1.0)
        comment = f"overlap_terms={sorted(overlap)[:10]}"
    return {"key": "final_answer_faithfulness", "score": score, "comment": comment}


EVALUATORS = (
    score_workflow_consistency,
    score_approval_gate,
    score_routing_choice,
    score_final_answer_faithfulness,
)


def seed_dataset() -> str:
    from langsmith import Client

    from agentmesh.testing.sanity_catalog import load_postgres_catalog, read_seeded_catalog

    client = Client(
        api_url=os.environ.get("LANGSMITH_ENDPOINT") or None,
        api_key=os.environ.get("LANGSMITH_API_KEY") or None,
    )
    dataset = next(client.list_datasets(dataset_name=DATASET_NAME, limit=1), None)
    if dataset is None:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description="AgentMesh smoke, integration, audit, and evaluator starter cases.",
        )
    existing_ids = {
        example.inputs.get("case_id") for example in client.list_examples(dataset_id=dataset.id)
    }
    try:
        cases = load_postgres_catalog(os.environ["DATABASE_URL"])
    except (KeyError, OSError):
        cases = read_seeded_catalog()
    for case in cases:
        if not case.langsmith_eval or case.case_id in existing_ids:
            continue
        client.create_example(
            dataset_id=dataset.id,
            inputs={
                "case_id": case.case_id,
                "component": case.component,
                "category": case.category,
                "prompt": case.command_hint,
            },
            outputs={"expected": case.expected},
            metadata={"priority": case.priority, "test_type": case.test_type},
        )
    return str(dataset.id)


def collect_live_workflow(api_url: str) -> dict[str, Any]:
    workflow = post_json(
        f"{api_url}/workflows/start",
        {
            "conversation_id": "langsmith-eval-live",
            "goal": "Draft one sanity sentence, then answer it with the multi-agent workflow.",
            "preferred_agent_ids": ["langgraph-copilot", "googleADK-Chatagent"],
        },
    )
    workflow_id = workflow["workflow_id"]
    while workflow.get("status") != "COMPLETED":
        if workflow.get("status") in {"AWAITING_PLAN_APPROVAL", "AWAITING_AGENT_APPROVAL"}:
            workflow = post_json(
                f"{api_url}/workflows/{workflow_id}/approvals",
                {"decision": "APPROVE", "actor": "langsmith-eval"},
            )
        else:
            workflow = get_json(f"{api_url}/workflows/{workflow_id}")
    events = get_json(f"{api_url}/events?workflow_id={workflow_id}")
    task_results = workflow.get("task_results", [])
    return {
        "status": workflow.get("status"),
        "planned_agents": [
            task["agent_id"] for task in (workflow.get("plan") or {}).get("tasks", [])
        ],
        "assigned_agents": workflow.get("assigned_agents", []),
        "event_types": [event["event_type"] for event in events],
        "previous_task_output": json.dumps(task_results[0], sort_keys=True) if task_results else "",
        "final_answer": json.dumps(task_results[-1], sort_keys=True) if task_results else "",
    }


def get_json(url: str) -> Any:
    with urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> Any:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed and run starter LangSmith evals.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--require-langsmith", action="store_true")
    args = parser.parse_args()
    load_dotenv(ENV_FILE)

    missing = [
        name
        for name in ("LANGSMITH_API_KEY", "LANGSMITH_PROJECT")
        if not os.environ.get(name)
    ]
    if missing:
        message = f"Missing LangSmith env vars: {missing}"
        if args.require_langsmith or os.getenv("AGENTMESH_REQUIRE_LANGSMITH") == "1":
            print(message, file=sys.stderr)
            return 1
        print(f"SKIP {message}")
        return 0

    dataset_id = seed_dataset()
    print(f"Dataset ready: {DATASET_NAME} ({dataset_id})")
    if args.seed_only:
        return 0

    outputs = collect_live_workflow(args.api_url.rstrip("/"))
    reference = {
        "status": "COMPLETED",
        "expected_agents": ["langgraph-copilot", "googleADK-Chatagent"],
        "required_events": ["PLAN_APPROVAL_REQUESTED", "PLAN_APPROVED", "AGENT_APPROVAL_REQUESTED"],
    }
    results = [evaluator(outputs, reference) for evaluator in EVALUATORS]
    print(json.dumps({"outputs": outputs, "evaluation_results": results}, indent=2))
    return 1 if any(result["score"] < 1.0 for result in results[:3]) else 0


if __name__ == "__main__":
    sys.exit(main())
