from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear AgentMesh LangSmith traces by recreating the configured project."
    )
    parser.add_argument(
        "--project",
        default=os.getenv("LANGSMITH_PROJECT"),
        help="Project to recreate. Defaults to LANGSMITH_PROJECT from .env.",
    )
    parser.add_argument(
        "--require-langsmith",
        action="store_true",
        help="Fail instead of skipping when LangSmith configuration is incomplete.",
    )
    args = parser.parse_args()
    load_dotenv(ENV_FILE)

    project_name = args.project or os.getenv("LANGSMITH_PROJECT")
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not project_name or not api_key:
        message = "Missing LANGSMITH_PROJECT or LANGSMITH_API_KEY."
        if args.require_langsmith or os.getenv("AGENTMESH_REQUIRE_LANGSMITH") == "1":
            print(message, file=sys.stderr)
            return 1
        print(f"SKIP {message}")
        return 0

    from langsmith import Client

    client = Client(
        api_url=os.getenv("LANGSMITH_ENDPOINT") or None,
        api_key=api_key,
        workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID") or None,
    )
    if client.has_project(project_name):
        client.delete_project(project_name=project_name)
        print(f"Deleted LangSmith project: {project_name}")
    client.create_project(
        project_name,
        description="AgentMesh smoke, UAT, and validation traces.",
        upsert=True,
    )
    print(f"Ready LangSmith project: {project_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
