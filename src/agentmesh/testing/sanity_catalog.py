from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[3]
UAT_CASES_DDL = ROOT / "deployment" / "postgres" / "ddls" / "008_agentmesh_uat_cases.sql"


@dataclass(frozen=True)
class SanityCase:
    case_id: str
    suite: str
    component: str
    category: str
    test_type: str
    execution_layer: str
    command_hint: str
    streamlit_surface: str
    expected: str
    priority: str = "P1"
    langsmith_eval: bool = False
    active: bool = True
    metadata: dict[str, Any] | None = None


def normalise_connection_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def load_postgres_catalog(database_url: str, *, active_only: bool = True) -> tuple[SanityCase, ...]:
    where = "WHERE active = TRUE" if active_only else ""
    with psycopg.connect(normalise_connection_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    case_id,
                    suite,
                    component,
                    category,
                    test_type,
                    execution_layer,
                    command_hint,
                    streamlit_surface,
                    expected,
                    priority,
                    langsmith_eval,
                    active,
                    metadata
                FROM agentmesh_uat_cases
                {where}
                ORDER BY priority, suite, case_id
                """
            )
            return tuple(SanityCase(*row) for row in cursor.fetchall())


def read_seeded_catalog(ddl_path: Path = UAT_CASES_DDL) -> tuple[SanityCase, ...]:
    """Read the DDL seed values for offline validation only.

    PostgreSQL remains the runtime source of truth. This parser lets unit tests
    verify the committed migration has the required UAT coverage before Docker
    is available.
    """

    sql = ddl_path.read_text(encoding="utf-8")
    values_match = re.search(
        r"INSERT INTO agentmesh_uat_cases\s*\([^)]*\)\s*VALUES\s*(.*?)\s*ON CONFLICT",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if values_match is None:
        raise ValueError(f"No seeded agentmesh_uat_cases values found in {ddl_path}")

    rows_literal = "[" + values_match.group(1).strip().rstrip(";") + "]"
    rows_literal = re.sub(r"'([^']*)'::jsonb", r"'\1'", rows_literal)
    rows_literal = re.sub(r"\bTRUE\b", "True", rows_literal, flags=re.IGNORECASE)
    rows_literal = re.sub(r"\bFALSE\b", "False", rows_literal, flags=re.IGNORECASE)
    rows = ast.literal_eval(rows_literal)
    return tuple(SanityCase(*row) for row in rows)


def cases_by_id(cases: tuple[SanityCase, ...] | None = None) -> dict[str, SanityCase]:
    selected = cases if cases is not None else read_seeded_catalog()
    return {case.case_id: case for case in selected}


def write_seeded_catalog_snapshot(path: Path, cases: tuple[SanityCase, ...] | None = None) -> None:
    selected = cases if cases is not None else read_seeded_catalog()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "case_id": case.case_id,
            "suite": case.suite,
            "component": case.component,
            "category": case.category,
            "test_type": case.test_type,
            "execution_layer": case.execution_layer,
            "command_hint": case.command_hint,
            "streamlit_surface": case.streamlit_surface,
            "expected": case.expected,
            "priority": case.priority,
            "langsmith_eval": case.langsmith_eval,
            "active": case.active,
            "metadata": case.metadata or {},
        }
        for case in selected
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
