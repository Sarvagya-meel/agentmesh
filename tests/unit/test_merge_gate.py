from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.tools.merge_gate import (
    active_waiver,
    aggregate_report,
    conventional_message_error,
    github_suite_durations,
    report_directory,
    suite_result,
    validate_report,
    validate_route,
)
from tests.tools.verify_release_branch import contains_latest_develop


def policy(*, required: bool = True, waivers: list[dict[str, object]] | None = None):
    return {
        "schema_version": 1,
        "suites": {"unit": {"required": required}},
        "waivers": waivers or [],
    }


def write_result(directory: Path, status: str = "pass") -> None:
    directory.mkdir(parents=True)
    (directory / "unit.json").write_text(
        json.dumps(suite_result("unit", status, "test result")), encoding="utf-8"
    )


def aggregate(tmp_path: Path, selected_policy=None):
    input_dir = tmp_path / "input"
    write_result(input_dir)
    return aggregate_report(
        input_dir,
        tmp_path / "report",
        selected_policy or policy(),
        pr_number=12,
        pr_created_at="2026-09-10T07:00:00Z",
        base_ref="develop",
        head_ref="feature/gate",
        head_sha="abc123",
        tested_sha="merge456",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )


def test_aggregate_writes_human_and_machine_reports(tmp_path: Path) -> None:
    report = aggregate(tmp_path)

    assert report["overall_status"] == "pass"
    assert (tmp_path / "report" / "gate-report.json").exists()
    assert (tmp_path / "report" / "gate-report.csv").exists()
    assert (tmp_path / "report" / "gate-report.md").exists()


def test_github_step_timestamps_produce_suite_durations() -> None:
    durations = github_suite_durations(
        {
            "jobs": [
                {
                    "steps": [
                        {
                            "name": "Unit tests",
                            "started_at": "2026-09-10T07:00:00Z",
                            "completed_at": "2026-09-10T07:00:05.500Z",
                        },
                        {
                            "name": "Install Playwright",
                            "started_at": "2026-09-10T07:01:00Z",
                            "completed_at": "2026-09-10T07:01:03Z",
                        },
                        {
                            "name": "Browser smoke",
                            "started_at": "2026-09-10T07:01:03Z",
                            "completed_at": "2026-09-10T07:01:05Z",
                        },
                    ]
                }
            ]
        }
    )

    assert durations["unit"] == 5.5
    assert durations["browser"] == 5.0


def test_missing_required_suite_fails(tmp_path: Path) -> None:
    report = aggregate_report(
        tmp_path / "empty",
        tmp_path / "report",
        policy(),
        pr_number=1,
        pr_created_at="2026-09-10T07:00:00Z",
        base_ref="develop",
        head_ref="fix/missing",
        head_sha="abc",
        tested_sha="def",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert report["overall_status"] == "fail"
    assert "unit: required result is missing" in report["problems"]


def test_optional_skip_requires_active_waiver(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    write_result(input_dir, "skip")
    waiver = {
        "suite": "unit",
        "owner": "@maintainer",
        "reason": "Temporary provider outage",
        "created_on": "2026-09-01",
        "expires_on": "2026-10-01",
    }

    report = aggregate_report(
        input_dir,
        tmp_path / "report",
        policy(required=False, waivers=[waiver]),
        pr_number=1,
        pr_created_at="2026-09-10T07:00:00Z",
        base_ref="develop",
        head_ref="fix/provider",
        head_sha="abc",
        tested_sha="def",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert report["overall_status"] == "pass"
    assert report["suites"][0]["accepted"] is True


def test_expired_and_overlong_waivers_are_rejected() -> None:
    expired = {
        "suite": "llm",
        "owner": "@maintainer",
        "reason": "Quota",
        "created_on": "2026-01-01",
        "expires_on": "2026-01-31",
    }
    overlong = {**expired, "expires_on": "2027-02-01"}

    today = datetime(2026, 9, 10).date()
    assert "expired" in (active_waiver("llm", [expired], today=today)[1] or "")
    assert "one-year" in (active_waiver("llm", [overlong], today=today)[1] or "")


def test_permanent_optional_waiver_requires_explicit_flag() -> None:
    waiver = {
        "suite": "browser",
        "owner": "@maintainer",
        "reason": "Not applicable",
        "expires_on": None,
    }

    error = active_waiver("browser", [waiver], today=datetime.now().date())[1]
    assert "permanent=true" in (error or "")
    accepted, error = active_waiver(
        "browser", [{**waiver, "permanent": True}], today=datetime.now().date()
    )
    assert error is None
    assert accepted is not None


def test_report_validation_rejects_sha_and_route_mismatch(tmp_path: Path) -> None:
    aggregate(tmp_path)
    report = tmp_path / "report" / "gate-report.json"

    errors = validate_report(
        report,
        head_sha="different",
        tested_sha="merge456",
        base_ref="main",
        head_ref="feature/gate",
    )

    assert any("head_sha" in error for error in errors)
    assert any("release/* or hotfix/*" in error for error in errors)


def test_missing_report_is_rejected(tmp_path: Path) -> None:
    errors = validate_report(
        tmp_path / "missing.json",
        head_sha="abc",
        tested_sha="def",
        base_ref="develop",
        head_ref="feature/test",
    )
    assert "does not exist" in errors[0]


def test_commit_and_branch_conventions() -> None:
    assert conventional_message_error("feat(gate): add report") is None
    assert conventional_message_error("not conventional") is not None
    assert validate_route("develop", "codex/reports") is None
    assert validate_route("develop", "release/v0.2.0") is None
    assert validate_route("main", "release/v0.2.0") is None
    assert validate_route("main", "feature/nope") is not None


def test_report_directory_uses_stable_pr_creation_date(tmp_path: Path) -> None:
    path = report_directory(tmp_path, "2026-09-10T07:00:00Z", 5, "abc")
    assert path == tmp_path / "2026-09-10" / "pr-5" / "abc"


def test_release_ancestry_requires_develop_to_be_the_merge_base() -> None:
    assert contains_latest_develop("develop-sha", "develop-sha")
    assert not contains_latest_develop("new-develop-sha", "old-develop-sha")
