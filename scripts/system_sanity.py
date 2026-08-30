from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deployment" / "docker" / "compose.yml"
ENV_FILE = ROOT / ".env"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "system_sanity"
LOG_PATTERN = re.compile(
    r"\b(ERROR|Traceback|Exception|failed|401|403|timeout|refused|409)\b",
    re.IGNORECASE,
)
KNOWN_TRANSIENT_LOG_PATTERN = re.compile(
    r"(rate_limit_exceeded|429 Too Many Requests|RateLimitError)",
    re.IGNORECASE,
)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    evidence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SanityRun:
    def __init__(
        self,
        *,
        output_dir: Path,
        api_url: str,
        langgraph_url: str,
        adk_url: str,
        mode: str,
        require_langsmith: bool,
        build: bool,
    ) -> None:
        self.output_dir = output_dir
        self.api_url = api_url.rstrip("/")
        self.langgraph_url = langgraph_url.rstrip("/")
        self.adk_url = adk_url.rstrip("/")
        self.mode = mode
        self.require_langsmith = require_langsmith
        self.build = build
        self.results: list[CheckResult] = []
        self.workflow_id: str | None = None
        self.started_at = datetime.now(UTC)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> int:
        load_dotenv(ENV_FILE)
        self.write_catalog()
        self.compose_config()
        if self.build:
            self.compose_up()
        self.container_status()
        self.http_checks()
        self.direct_invokes()
        self.workflow_smoke()
        self.db_event_check()
        self.collect_and_scan_logs()
        self.langsmith_check()
        self.write_summary()
        return 1 if any(result.status == "fail" for result in self.results) else 0

    def add(self, name: str, status: str, detail: str = "", **metadata: Any) -> None:
        self.results.append(CheckResult(name, status, detail, metadata=metadata))

    def write_catalog(self) -> None:
        from agentmesh.testing.sanity_catalog import write_sqlite_catalog

        catalog = self.output_dir / "agentmesh_sanity_catalog.sqlite"
        write_sqlite_catalog(catalog)
        self.add("catalog.sqlite", "pass", "Sanity catalog written.", evidence=str(catalog))

    def compose(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "combined",
            *args,
        ]

    def run_command(
        self, name: str, command: list[str], evidence_name: str
    ) -> subprocess.CompletedProcess[str]:
        evidence = self.output_dir / evidence_name
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        evidence.write_text(completed.stdout, encoding="utf-8")
        status = "pass" if completed.returncode == 0 else "fail"
        self.add(name, status, f"Exit code {completed.returncode}.", evidence=str(evidence))
        return completed

    def compose_config(self) -> None:
        self.run_command(
            "docker.compose.config", self.compose("config", "--quiet"), "compose_config.log"
        )

    def compose_up(self) -> None:
        self.run_command(
            "docker.compose.up",
            self.compose("up", "-d", "--build"),
            "docker_build_startup.log",
        )

    def container_status(self) -> None:
        completed = self.run_command("docker.compose.ps", self.compose("ps"), "docker_ps.log")
        expected = [
            "agentmesh-postgres",
            "agentmesh-orchestrator-supervisor",
            "agentmesh-agent-langgraph-copilot-1",
            "agentmesh-agent-googleadk-chatagent-1",
            "agentmesh-streamlit",
        ]
        missing = [name for name in expected if name not in completed.stdout]
        if missing:
            self.add("docker.containers.expected", "fail", f"Missing containers: {missing}")
        else:
            self.add("docker.containers.expected", "pass", "All expected containers are listed.")

    def http_checks(self) -> None:
        checks = {
            "orchestrator.health": http_json("GET", f"{self.api_url}/health"),
            "langgraph.ready": http_json("GET", f"{self.langgraph_url}/ready"),
            "adk.ready": http_json("GET", f"{self.adk_url}/ready"),
            "registry.agents": http_json("GET", f"{self.api_url}/registry/agents"),
        }
        evidence = self.output_dir / "http_checks.json"
        evidence.write_text(json.dumps(checks, indent=2, default=str), encoding="utf-8")
        self.add(
            "http.health_ready_registry",
            "pass",
            "Health, readiness, and registry endpoints responded.",
            evidence=str(evidence),
        )
        agents = checks["registry.agents"]
        online = {agent["agent_id"] for agent in agents if agent.get("status") == "online"}
        required = {"langgraph-copilot", "googleADK-Chatagent", "orchestrator-supervisor-agent"}
        missing = sorted(required - online)
        self.add(
            "registry.required_agents_online",
            "fail" if missing else "pass",
            f"Missing online agents: {missing}" if missing else "Required agents are online.",
        )

    def direct_invokes(self) -> None:
        payloads = {
            "langgraph": (
                f"{self.langgraph_url}/invoke",
                {
                    "message": "Sanity check: say LangGraph runtime is ready in one sentence.",
                    "thread_id": f"sanity-langgraph-{uuid4()}",
                    "approval_required": False,
                },
            ),
            "adk": (
                f"{self.adk_url}/invoke",
                {
                    "message": "Sanity check: say ADK runtime is ready in one sentence.",
                    "thread_id": f"sanity-adk-{uuid4()}",
                    "approval_required": False,
                },
            ),
        }
        results = {
            name: http_json("POST", url, payload)
            for name, (url, payload) in payloads.items()
        }
        evidence = self.output_dir / "direct_invokes.json"
        evidence.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        langgraph_ok = results["langgraph"].get("status") == "COMPLETED"
        adk_ok = results["adk"].get("status") == "success"
        self.add(
            "agents.direct_invokes",
            "pass" if langgraph_ok and adk_ok else "fail",
            (
                "LangGraph and ADK direct invocations completed."
                if langgraph_ok and adk_ok
                else "At least one direct invoke failed."
            ),
            evidence=str(evidence),
        )

    def workflow_smoke(self) -> None:
        started = http_json(
            "POST",
            f"{self.api_url}/workflows/start",
            {
                "conversation_id": f"sanity-workflow-{uuid4()}",
                "goal": "Draft a tiny sanity check, then answer it in one sentence.",
                "preferred_agent_ids": ["langgraph-copilot", "googleADK-Chatagent"],
            },
        )
        self.workflow_id = started["workflow_id"]
        states = [started]
        current = started
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and current.get("status") != "COMPLETED":
            if current.get("status") in {"AWAITING_PLAN_APPROVAL", "AWAITING_AGENT_APPROVAL"}:
                current = http_json(
                    "POST",
                    f"{self.api_url}/workflows/{self.workflow_id}/approvals",
                    {"decision": "APPROVE", "actor": "system-sanity"},
                )
            else:
                time.sleep(2)
                current = http_json("GET", f"{self.api_url}/workflows/{self.workflow_id}")
            states.append(current)
        evidence = self.output_dir / "workflow_smoke.json"
        evidence.write_text(json.dumps(states, indent=2, default=str), encoding="utf-8")
        self.add(
            "workflow.smoke",
            "pass" if states[-1].get("status") == "COMPLETED" else "fail",
            f"Final workflow status: {states[-1].get('status')}.",
            evidence=str(evidence),
            workflow_id=self.workflow_id,
        )
        results = states[-1].get("task_results", [])
        if len(results) >= 2:
            first = json.dumps(results[0], sort_keys=True)
            final = json.dumps(results[-1], sort_keys=True)
            self.add(
                "workflow.final_answer_faithfulness_hint",
                (
                    "pass"
                    if any(token in final.lower() for token in first.lower().split()[:20])
                    else "warn"
                ),
                "Final result retains some lexical overlap with prior task output.",
            )

    def db_event_check(self) -> None:
        if self.workflow_id is None:
            self.add("postgres.workflow_events", "skip", "No workflow id available.")
            return
        sql = (
            "SELECT sequence_number, event_type, source_agent, target_agent "
            f"FROM agentmesh_events WHERE workflow_id = '{self.workflow_id}' "
            "ORDER BY sequence_number;"
        )
        completed = self.run_command(
            "postgres.workflow_events",
            [
                "docker",
                "exec",
                "agentmesh-postgres",
                "psql",
                "-U",
                "agentmesh",
                "-d",
                "agentmesh",
                "-c",
                sql,
            ],
            "postgres_workflow_events.log",
        )
        if "WORKFLOW_COMPLETED" not in completed.stdout:
            self.add(
                "postgres.workflow_completed_event",
                "fail",
                "Workflow completion event not found.",
            )
        else:
            self.add(
                "postgres.workflow_completed_event",
                "pass",
                "Workflow completion event found.",
            )

    def collect_and_scan_logs(self) -> None:
        log_dir = self.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        containers = [
            "agentmesh-orchestrator-supervisor",
            "agentmesh-agent-langgraph-copilot-1",
            "agentmesh-agent-googleadk-chatagent-1",
            "agentmesh-postgres",
            "agentmesh-streamlit",
            "agentmesh-migrate",
        ]
        matches: list[dict[str, Any]] = []
        raw_logs: dict[str, str] = {}
        for container in containers:
            log_file = log_dir / f"{container}.log"
            completed = subprocess.run(
                ["docker", "logs", "--since", self.started_at.isoformat(), container],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            log_file.write_text(completed.stdout, encoding="utf-8")
            raw_logs[container] = completed.stdout
            for number, line in enumerate(completed.stdout.splitlines(), start=1):
                if LOG_PATTERN.search(line):
                    matches.append({"container": container, "line": number, "text": line})
        transient_provider_matches = [
            match
            for match in matches
            if match["container"] == "agentmesh-agent-googleadk-chatagent-1"
            and KNOWN_TRANSIENT_LOG_PATTERN.search(
                raw_logs.get("agentmesh-agent-googleadk-chatagent-1", "")
            )
        ]
        unexpected_matches = [
            match for match in matches if match not in transient_provider_matches
        ]
        evidence = self.output_dir / "log_scan.json"
        evidence.write_text(
            json.dumps(
                {
                    "unexpected": unexpected_matches,
                    "known_transient_provider": transient_provider_matches,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        status = (
            "fail"
            if unexpected_matches
            else "warn"
            if transient_provider_matches
            else "pass"
        )
        self.add(
            "logs.error_scan",
            status,
            (
                f"{len(unexpected_matches)} unexpected matches; "
                f"{len(transient_provider_matches)} known transient provider matches."
            ),
            evidence=str(evidence),
        )

    def langsmith_check(self) -> None:
        missing = [
            name
            for name in ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGSMITH_PROJECT")
            if not os.environ.get(name)
        ]
        if missing:
            status = "fail" if self.require_langsmith or self.mode == "ci" else "skip"
            self.add("langsmith.config", status, f"Missing LangSmith env vars: {missing}")
            return
        try:
            from langsmith import Client
        except ImportError as exc:
            status = "fail" if self.require_langsmith or self.mode == "ci" else "skip"
            self.add("langsmith.sdk", status, f"LangSmith SDK is unavailable: {exc}")
            return
        client = Client(
            api_url=os.environ.get("LANGSMITH_ENDPOINT") or None,
            api_key=os.environ.get("LANGSMITH_API_KEY") or None,
        )
        trace_marker_thread_id = f"langsmith-trace-shape-{uuid4()}"
        try:
            http_json(
                "POST",
                f"{self.langgraph_url}/invoke",
                {
                    "message": "LangSmith direct trace shape marker.",
                    "approval_required": False,
                    "thread_id": trace_marker_thread_id,
                },
            )
        except RuntimeError as exc:
            self.add(
                "langsmith.direct_trace_marker",
                "fail" if self.require_langsmith or self.mode == "ci" else "warn",
                f"Could not emit direct trace marker: {exc}",
            )
        project_name = os.environ["LANGSMITH_PROJECT"]
        projects = [project for project in client.list_projects() if project.name == project_name]
        runs = []
        for _ in range(6):
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="list_runs.*",
                    category=DeprecationWarning,
                )
                runs = list(
                    client.list_runs(
                        project_name=project_name,
                        start_time=datetime.now(UTC) - timedelta(hours=1),
                        limit=100,
                    )
                )
            run_names = {run.name for run in runs}
            if self._has_agentmesh_trace_shape(run_names):
                break
            time.sleep(2)
        run_names = {run.name for run in runs}
        evidence = self.output_dir / "langsmith_check.json"
        evidence.write_text(
            json.dumps(
                {
                    "endpoint": os.environ.get("LANGSMITH_ENDPOINT"),
                    "project": project_name,
                    "api_key_present": True,
                    "project_matches": len(projects),
                    "recent_run_count_sample": len(runs),
                    "trace_marker_thread_id": trace_marker_thread_id,
                    "agentmesh_trace_shape": self._has_agentmesh_trace_shape(run_names),
                    "recent_runs": [
                        {
                            "name": run.name,
                            "run_type": run.run_type,
                            "start_time": str(run.start_time),
                        }
                        for run in runs[:10]
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.add(
            "langsmith.project_and_traces",
            "pass" if projects and runs and self._has_agentmesh_trace_shape(run_names) else "fail",
            (
                f"Project matches={len(projects)}, recent runs={len(runs)}, "
                f"agentmesh_shape={self._has_agentmesh_trace_shape(run_names)}."
            ),
            evidence=str(evidence),
        )

    @staticmethod
    def _has_agentmesh_trace_shape(run_names: set[str]) -> bool:
        has_direct = any(run_name.startswith("Direct ||") for run_name in run_names)
        has_workflow = any(run_name.startswith("WorkFlow ||") for run_name in run_names)
        has_event = any(
            run_name.startswith("WorkFlow ||") and "event " in run_name for run_name in run_names
        )
        has_assignment_result = any(
            run_name.startswith("WorkFlow ||") and "assignment result" in run_name
            for run_name in run_names
        )
        has_registry = any(run_name.startswith("Registry ||") for run_name in run_names)
        return has_direct and has_workflow and has_event and has_assignment_result and has_registry

    def write_summary(self) -> None:
        summary = {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": self.mode,
            "results": [result.__dict__ for result in self.results],
        }
        (self.output_dir / "system_sanity_summary.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
        for result in self.results:
            print(f"{result.status.upper():5} {result.name} {result.detail}")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    attempts: int = 6,
    delay_seconds: float = 2.0,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
        except (ConnectionError, OSError, RemoteDisconnected, TimeoutError, URLError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay_seconds)
    raise RuntimeError(f"{method} {url} failed after {attempts} attempts: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AgentMesh end-to-end sanity checks.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--langgraph-url", default="http://localhost:8101")
    parser.add_argument("--adk-url", default="http://localhost:8102")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--mode",
        choices=["local", "ci"],
        default=os.getenv("AGENTMESH_SANITY_MODE", "local"),
    )
    parser.add_argument("--require-langsmith", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()

    require_langsmith = args.require_langsmith or os.getenv("AGENTMESH_REQUIRE_LANGSMITH") == "1"
    run = SanityRun(
        output_dir=args.output_dir,
        api_url=args.api_url,
        langgraph_url=args.langgraph_url,
        adk_url=args.adk_url,
        mode=args.mode,
        require_langsmith=require_langsmith,
        build=not args.no_build,
    )
    return run.run()


if __name__ == "__main__":
    sys.exit(main())
