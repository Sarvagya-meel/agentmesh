from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / ".github" / "test-policy.yml"
REPORT_SCHEMA_VERSION = 1
CONVENTIONAL_COMMIT = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([a-zA-Z0-9._/-]+\))?(!)?: .+"
)
ALLOWED_DEVELOP_PREFIXES = (
    "feature/",
    "fix/",
    "chore/",
    "docs/",
    "test/",
    "codex/",
    "release/",
    "hotfix/",
)
ALLOWED_MAIN_PREFIXES = ("release/", "hotfix/")


def utc_now() -> datetime:
    return datetime.now(UTC)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    policy = load_json(path)
    if policy.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported test policy schema in {path}")
    suites = policy.get("suites")
    if not isinstance(suites, dict) or not suites:
        raise ValueError(f"{path} must define at least one suite")
    return policy


def normalise_status(status: str) -> str:
    return {
        "success": "pass",
        "passed": "pass",
        "failure": "fail",
        "failed": "fail",
        "cancelled": "fail",
        "canceled": "fail",
        "skipped": "skip",
    }.get(status.lower(), status.lower())


def suite_result(
    suite: str,
    status: str,
    detail: str,
    *,
    duration_seconds: float = 0.0,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite": suite,
        "status": normalise_status(status),
        "detail": detail,
        "duration_seconds": round(duration_seconds, 3),
        "generated_at": (generated_at or utc_now()).isoformat(),
    }


def write_suite_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def parse_iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def active_waiver(
    suite: str,
    waivers: Sequence[dict[str, Any]],
    *,
    today: date,
) -> tuple[dict[str, Any] | None, str | None]:
    waiver = next((item for item in waivers if item.get("suite") == suite), None)
    if waiver is None:
        return None, "no waiver is configured"
    if not waiver.get("owner") or not waiver.get("reason"):
        return None, "waiver must include owner and reason"
    expires_on = waiver.get("expires_on")
    if expires_on is None:
        if waiver.get("permanent") is True:
            return waiver, None
        return None, "an indefinite waiver must set permanent=true"
    created_on = parse_iso_date(str(waiver.get("created_on", "")), "created_on")
    expiry = parse_iso_date(str(expires_on), "expires_on")
    if expiry < created_on:
        return None, "waiver expires before it starts"
    if expiry - created_on > timedelta(days=365):
        return None, "temporary waiver exceeds the one-year maximum"
    if expiry < today:
        return None, f"waiver expired on {expiry.isoformat()}"
    return waiver, None


def evaluate_suites(
    results: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    *,
    today: date,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    evaluated: list[dict[str, Any]] = []
    problems: list[str] = []
    applied_waivers: list[dict[str, Any]] = []
    waivers = policy.get("waivers", [])
    if not isinstance(waivers, list):
        raise ValueError("test policy waivers must be a list")

    for suite, suite_policy in policy["suites"].items():
        required = bool(suite_policy.get("required", True))
        result = dict(
            results.get(
                suite,
                suite_result(suite, "missing", "Suite did not produce a result."),
            )
        )
        status = normalise_status(str(result.get("status", "missing")))
        result["status"] = status
        result["required"] = required
        result["accepted"] = status == "pass"
        result["waiver"] = None

        if status != "pass":
            if required or status not in {"skip", "warn"}:
                problems.append(f"{suite}: required result is {status}")
            else:
                waiver, error = active_waiver(suite, waivers, today=today)
                if error:
                    problems.append(f"{suite}: {status} is not allowed because {error}")
                else:
                    result["accepted"] = True
                    result["waiver"] = waiver
                    applied_waivers.append(waiver or {})
        evaluated.append(result)
    return evaluated, problems, applied_waivers


def report_counts(suites: Sequence[dict[str, Any]]) -> dict[str, int]:
    statuses = ("pass", "fail", "warn", "skip", "missing")
    return {
        status: sum(1 for suite in suites if suite.get("status") == status)
        for status in statuses
    }


def markdown_report(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# AgentMesh Merge Gate",
        "",
        f"- Overall status: `{report['overall_status']}`",
        f"- PR: `#{report['pr_number']}` (`{report['head_ref']}` -> `{report['base_ref']}`)",
        f"- Head SHA: `{report['head_sha']}`",
        f"- Tested SHA: `{report['tested_sha']}`",
        (
            "- Counts: "
            f"pass `{counts['pass']}`, fail `{counts['fail']}`, warn `{counts['warn']}`, "
            f"skip `{counts['skip']}`, missing `{counts['missing']}`"
        ),
        "",
        "| Suite | Required | Status | Accepted | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for suite in report["suites"]:
        detail = str(suite.get("detail", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{suite['suite']}` | `{suite['required']}` | `{suite['status']}` | "
            f"`{suite['accepted']}` | {detail} |"
        )
    if report["problems"]:
        lines.extend(["", "## Blocking Problems", ""])
        lines.extend(f"- {problem}" for problem in report["problems"])
    lines.extend(
        [
            "",
            "The JSON report is authoritative for automation; CSV is provided "
            "for spreadsheet review.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gate-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    with (output_dir / "gate-report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "suite",
                "required",
                "status",
                "accepted",
                "duration_seconds",
                "detail",
            ],
        )
        writer.writeheader()
        for suite in report["suites"]:
            writer.writerow({field: suite.get(field, "") for field in writer.fieldnames})
    (output_dir / "gate-report.md").write_text(markdown_report(report), encoding="utf-8")


def aggregate_report(
    input_dir: Path,
    output_dir: Path,
    policy: dict[str, Any],
    *,
    pr_number: int,
    pr_created_at: str,
    base_ref: str,
    head_ref: str,
    head_sha: str,
    tested_sha: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    raw_results: dict[str, dict[str, Any]] = {}
    for path in sorted(input_dir.rglob("*.json")):
        result = load_json(path)
        suite = result.get("suite")
        if isinstance(suite, str):
            raw_results[suite] = result
    suites, problems, waivers = evaluate_suites(raw_results, policy, today=current.date())
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": current.isoformat(),
        "pr_created_at": pr_created_at,
        "pr_number": pr_number,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "tested_sha": tested_sha,
        "overall_status": "pass" if not problems else "fail",
        "counts": report_counts(suites),
        "suites": suites,
        "applied_waivers": waivers,
        "problems": problems,
    }
    write_reports(output_dir, report)
    return report


def report_directory(root: Path, pr_created_at: str, pr_number: int, head_sha: str) -> Path:
    created = datetime.fromisoformat(pr_created_at.replace("Z", "+00:00")).date().isoformat()
    return root / created / f"pr-{pr_number}" / head_sha


def validate_route(base_ref: str, head_ref: str) -> str | None:
    if base_ref == "develop" and not head_ref.startswith(ALLOWED_DEVELOP_PREFIXES):
        return f"PRs into develop must come from {', '.join(ALLOWED_DEVELOP_PREFIXES)}"
    if base_ref == "main" and not head_ref.startswith(ALLOWED_MAIN_PREFIXES):
        return "PRs into main must come from release/* or hotfix/*"
    if base_ref not in {"develop", "main"}:
        return f"unsupported protected base branch: {base_ref}"
    return None


def validate_report(
    path: Path,
    *,
    head_sha: str,
    tested_sha: str,
    base_ref: str,
    head_ref: str,
) -> list[str]:
    if not path.exists():
        return [f"consolidated report does not exist at {path}"]
    try:
        report = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"consolidated report is unreadable: {exc}"]
    errors: list[str] = []
    expected = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "head_sha": head_sha,
        "tested_sha": tested_sha,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "overall_status": "pass",
    }
    for field, value in expected.items():
        if report.get(field) != value:
            errors.append(f"{field} expected {value!r}, found {report.get(field)!r}")
    errors.extend(str(item) for item in report.get("problems", []))
    route_error = validate_route(base_ref, head_ref)
    if route_error:
        errors.append(route_error)
    return errors


def conventional_message_error(message: str) -> str | None:
    first_line = message.splitlines()[0].strip() if message.splitlines() else ""
    if first_line.startswith(("Merge ", "Revert \"")):
        return None
    if CONVENTIONAL_COMMIT.fullmatch(first_line):
        return None
    return (
        "commit message must follow Conventional Commits, for example "
        "feat(scope): add capability"
    )


def run_commands(commands: Sequence[Sequence[str]]) -> tuple[str, float, str]:
    started = time.monotonic()
    failures: list[str] = []
    for command in commands:
        print(f"+ {' '.join(command)}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode:
            failures.append(f"{' '.join(command)} exited {completed.returncode}")
    duration = time.monotonic() - started
    return ("fail" if failures else "pass", duration, "; ".join(failures) or "All commands passed.")


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def run_local(output_root: Path) -> int:
    python = sys.executable
    commands = {
        "static": [
            [python, "-m", "ruff", "check", "src", "tests"],
            [python, "-m", "mypy", "--strict", "src"],
            [python, "tests/tools/export_langgraph_mermaid.py", "--check"],
        ],
        "unit": [[python, "-m", "pytest", "tests/unit", "-q"]],
        "integration": [[python, "-m", "pytest", "tests/api", "-q"]],
    }
    results: list[dict[str, Any]] = []
    for suite, suite_commands in commands.items():
        status, duration, detail = run_commands(suite_commands)
        results.append(suite_result(suite, status, detail, duration_seconds=duration))
    head_sha = git_value("rev-parse", "HEAD")
    branch = git_value("branch", "--show-current")
    output_dir = output_root / utc_now().date().isoformat() / head_sha
    problems = [
        f"{item['suite']}: {item['status']}"
        for item in results
        if item["status"] != "pass"
    ]
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": utc_now().isoformat(),
        "pr_created_at": "local",
        "pr_number": 0,
        "base_ref": "develop",
        "head_ref": branch,
        "head_sha": head_sha,
        "tested_sha": head_sha,
        "overall_status": "pass" if not problems else "fail",
        "counts": report_counts(results),
        "suites": [
            {**item, "required": True, "accepted": item["status"] == "pass"}
            for item in results
        ],
        "applied_waivers": [],
        "problems": problems,
    }
    write_reports(output_dir, report)
    print(f"Local merge-gate report: {output_dir / 'gate-report.json'}")
    return int(bool(problems))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentMesh merge-gate utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record-suite")
    record.add_argument("--suite", required=True)
    record.add_argument("--status", required=True)
    record.add_argument("--detail", default="")
    record.add_argument("--duration-seconds", type=float, default=0.0)
    record.add_argument("--output", type=Path, required=True)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--input-dir", type=Path, required=True)
    aggregate.add_argument("--output-root", type=Path, required=True)
    aggregate.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    aggregate.add_argument("--pr-number", type=int, required=True)
    aggregate.add_argument("--pr-created-at", required=True)
    aggregate.add_argument("--base-ref", required=True)
    aggregate.add_argument("--head-ref", required=True)
    aggregate.add_argument("--head-sha", required=True)
    aggregate.add_argument("--tested-sha", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--head-sha", required=True)
    verify.add_argument("--tested-sha", required=True)
    verify.add_argument("--base-ref", required=True)
    verify.add_argument("--head-ref", required=True)

    message = subparsers.add_parser("validate-message")
    message.add_argument("message_file", type=Path)

    title = subparsers.add_parser("validate-pr")
    title.add_argument("--title", required=True)
    title.add_argument("--base-ref", required=True)
    title.add_argument("--head-ref", required=True)

    local = subparsers.add_parser("local")
    local.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "outputs" / "test-reports" / "local",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "record-suite":
        write_suite_result(
            args.output,
            suite_result(
                args.suite,
                args.status,
                args.detail,
                duration_seconds=args.duration_seconds,
            ),
        )
        return 0
    if args.command == "aggregate":
        output_dir = report_directory(
            args.output_root, args.pr_created_at, args.pr_number, args.head_sha
        )
        report = aggregate_report(
            args.input_dir,
            output_dir,
            load_policy(args.policy),
            pr_number=args.pr_number,
            pr_created_at=args.pr_created_at,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            head_sha=args.head_sha,
            tested_sha=args.tested_sha,
        )
        print(output_dir / "gate-report.json")
        return int(report["overall_status"] != "pass")
    if args.command == "verify":
        errors = validate_report(
            args.report,
            head_sha=args.head_sha,
            tested_sha=args.tested_sha,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
        for error in errors:
            print(f"::error::PR not allowed: {error}")
        return int(bool(errors))
    if args.command == "validate-message":
        error = conventional_message_error(args.message_file.read_text(encoding="utf-8"))
        if error:
            print(f"ERROR: {error}", file=sys.stderr)
        return int(error is not None)
    if args.command == "validate-pr":
        errors = [
            error
            for error in (
                conventional_message_error(args.title),
                validate_route(args.base_ref, args.head_ref),
            )
            if error
        ]
        for error in errors:
            print(f"::error::{error}")
        return int(bool(errors))
    if args.command == "local":
        return run_local(args.output_root)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
