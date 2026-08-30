from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SanityCase:
    case_id: str
    component: str
    category: str
    test_type: str
    command_hint: str
    expected: str
    priority: str = "P1"
    langsmith_eval: bool = False


SANITY_CASES: tuple[SanityCase, ...] = (
    SanityCase(
        "docker.compose.config",
        "docker",
        "startup",
        "smoke",
        "docker compose --env-file .env -f deployment/docker/compose.yml "
        "--profile combined config --quiet",
        "Compose renders without validation errors.",
        "P0",
    ),
    SanityCase(
        "docker.compose.build",
        "docker",
        "startup",
        "smoke",
        "docker compose --env-file .env -f deployment/docker/compose.yml "
        "--profile combined up -d --build",
        "Images build and services reach their health gates.",
        "P0",
    ),
    SanityCase(
        "orchestrator.health",
        "orchestrator",
        "runtime",
        "smoke",
        "GET /health",
        "The orchestrator returns status ok.",
        "P0",
    ),
    SanityCase(
        "langgraph.ready",
        "langgraph-agent",
        "runtime",
        "smoke",
        "GET /ready",
        "LangGraph runtime reports ready and combined/worker role.",
        "P0",
    ),
    SanityCase(
        "adk.ready",
        "adk-agent",
        "runtime",
        "smoke",
        "GET /ready",
        "Google ADK runtime reports ready and combined/worker role.",
        "P0",
    ),
    SanityCase(
        "registry.online_agents",
        "registry",
        "runtime",
        "integration",
        "GET /registry/agents",
        "LangGraph, Google ADK, and orchestrator cards are online.",
        "P0",
    ),
    SanityCase(
        "invoke.langgraph",
        "langgraph-agent",
        "runtime",
        "functional",
        "POST /invoke",
        "LangGraph direct invocation completes with a final reply.",
        "P0",
        True,
    ),
    SanityCase(
        "invoke.adk",
        "adk-agent",
        "runtime",
        "functional",
        "POST /invoke",
        "Google ADK direct invocation succeeds with a final reply.",
        "P0",
        True,
    ),
    SanityCase(
        "workflow.approval_gates",
        "workflow",
        "runtime",
        "integration",
        "POST /workflows/start and /workflows/{id}/approvals",
        "The workflow passes plan approval, agent output approval, and completion.",
        "P0",
        True,
    ),
    SanityCase(
        "events.workflow_audit",
        "events",
        "audit",
        "integration",
        "GET /events?workflow_id=...",
        "Workflow audit events include planning, assignment, approval, and completion.",
        "P0",
        True,
    ),
    SanityCase(
        "claims.no_reclaim_pending_approval",
        "workers",
        "runtime",
        "unit",
        "list_pending_assignments",
        "Assignments that already proposed output do not re-enter the worker queue.",
        "P0",
    ),
    SanityCase(
        "langsmith.project_auth",
        "langsmith",
        "observability",
        "smoke",
        "LangSmith Client list projects and recent runs",
        "Configured project is reachable and recent traces are visible.",
        "P0",
        True,
    ),
    SanityCase(
        "postgres.workflow_events",
        "postgres",
        "persistence",
        "integration",
        "SELECT event_type FROM agentmesh_events WHERE workflow_id = ...",
        "Durable events exist in expected workflow order.",
        "P1",
    ),
    SanityCase(
        "logs.no_runtime_errors",
        "observability",
        "runtime",
        "non-functional",
        "docker logs scan",
        "Runtime logs contain no fatal errors or auth failures after smoke checks.",
        "P1",
    ),
)


def write_sqlite_catalog(path: Path, cases: Iterable[SanityCase] = SANITY_CASES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sanity_cases (
                case_id TEXT PRIMARY KEY,
                component TEXT NOT NULL,
                category TEXT NOT NULL,
                test_type TEXT NOT NULL,
                command_hint TEXT NOT NULL,
                expected TEXT NOT NULL,
                priority TEXT NOT NULL,
                langsmith_eval INTEGER NOT NULL
            )
            """
        )
        connection.execute("DELETE FROM sanity_cases")
        connection.executemany(
            """
            INSERT INTO sanity_cases (
                case_id, component, category, test_type, command_hint,
                expected, priority, langsmith_eval
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    case.case_id,
                    case.component,
                    case.category,
                    case.test_type,
                    case.command_hint,
                    case.expected,
                    case.priority,
                    int(case.langsmith_eval),
                )
                for case in cases
            ],
        )
        connection.execute(
            """
            CREATE VIEW IF NOT EXISTS v_langsmith_eval_cases AS
            SELECT * FROM sanity_cases WHERE langsmith_eval = 1
            """
        )
        connection.execute(
            """
            CREATE VIEW IF NOT EXISTS v_priority_summary AS
            SELECT priority, test_type, COUNT(*) AS case_count
            FROM sanity_cases
            GROUP BY priority, test_type
            """
        )


def cases_by_id() -> dict[str, SanityCase]:
    return {case.case_id: case for case in SANITY_CASES}
