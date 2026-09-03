"""Repeat the full demo acceptance sequence on fresh project-scoped Docker data."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-data",
        action="store_true",
        required=True,
        help="Confirm deletion of AgentMesh containers, images and database volume.",
    )
    parser.add_argument("--rounds", type=int, choices=[1, 2], default=2)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "outputs/system_sanity/demo_final"
    )
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "deployment/docker/compose.yml"),
    ]
    config = json.loads(subprocess.check_output([*compose, "config", "--format", "json"], cwd=ROOT))
    if config.get("name") != "agentmesh":
        raise ValueError("Refusing to reset a Compose project other than agentmesh.")
    results = []
    environment = dict(os.environ)
    environment.pop("AGENTMESH_LIVE_UAT", None)
    python = sys.executable
    for round_number in range(1, args.rounds + 1):
        output = args.output_dir.resolve() / f"round{round_number}"
        output.mkdir(parents=True, exist_ok=True)

        def run(
            name: str,
            command: list[str],
            *,
            live: bool = False,
            round_number: int = round_number,
            output: Path = output,
        ) -> bool:
            print(f"Round {round_number}: {name}", flush=True)
            env = {**environment, **({"AGENTMESH_LIVE_UAT": "1"} if live else {})}
            with (output / f"{name}.log").open("w", encoding="utf-8") as log:
                process = subprocess.run(
                    command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=False
                )
            results.append({"round": round_number, "check": name, "exit_code": process.returncode})
            (args.output_dir / "summary.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            print(
                f"  {'PASS' if process.returncode == 0 else 'FAIL'} (exit {process.returncode})",
                flush=True,
            )
            return process.returncode == 0

        run("ruff", [python, "-m", "ruff", "check", "src", "tests", "scripts"])
        run("mypy", [python, "-m", "mypy", "--strict", "--no-incremental", "src"])
        run("graphs", [python, "scripts/export_langgraph_mermaid.py", "--check"])
        run(
            "pytest",
            [python, "-m", "pytest", "-q", "--cache-clear", f"--junitxml={output / 'pytest.xml'}"],
        )
        if not run("reset", [*compose, "down", "--volumes", "--rmi", "local", "--remove-orphans"]):
            return 1
        if not run("build", [*compose, "build", "--no-cache", "--pull"]):
            return 1
        if not run("startup", [*compose, "up", "-d", "--wait", "--wait-timeout", "240"]):
            return 1
        run(
            "live",
            [
                python,
                "-m",
                "pytest",
                "tests/live",
                "-q",
                "--cache-clear",
                f"--junitxml={output / 'live.xml'}",
            ],
            live=True,
        )
        run(
            "sanity",
            [
                python,
                "scripts/system_sanity.py",
                "--no-build",
                "--output-dir",
                str(output / "sanity"),
            ],
        )
        run("browser", [args.node, "scripts/browser_smoke.cjs", str(output / "browser")])
    return int(any(result["exit_code"] for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
