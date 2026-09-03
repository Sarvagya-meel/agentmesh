from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, arguments: list[str]) -> bool:
    print(f"==> {label}", flush=True)
    completed = subprocess.run(arguments, cwd=ROOT, check=False)
    return completed.returncode == 0


def main() -> int:
    python = sys.executable
    checks = [
        ("Ruff", [python, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("Mypy", [python, "-m", "mypy", "src/agentmesh"]),
        ("Pytest", [python, "-m", "pytest", "-q"]),
    ]
    failed = [label for label, command in checks if not run(label, command)]
    if failed:
        print("Failed checks: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("All local validation checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

