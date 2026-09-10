from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
NON_FUNCTIONAL_FILES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".github/CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
}


def is_non_functional(path: str) -> bool:
    """Return whether a changed path cannot affect the built application."""
    normalized = PurePosixPath(path).as_posix()
    return (
        normalized in NON_FUNCTIONAL_FILES
        or normalized.startswith("docs/")
        or normalized.startswith(".github/ISSUE_TEMPLATE/")
        or normalized.endswith(".md")
    )


def requires_full_system(paths: Sequence[str]) -> bool:
    """Require full-system coverage when any changed path is functional."""
    return not paths or any(not is_non_functional(path) for path in paths)


def changed_paths(base: str, head: str) -> list[str]:
    """Return paths changed between the PR base and head revisions."""
    output = subprocess.check_output(
        ["git", "diff", "--name-only", base, head],
        cwd=ROOT,
        text=True,
    )
    return [line for line in output.splitlines() if line]


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(description="Classify full-system test scope")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write the full-system decision for a GitHub Actions step."""
    args = build_parser().parse_args(argv)
    paths = changed_paths(args.base, args.head)
    required = requires_full_system(paths)
    reason = "functional changes detected" if required else "non-functional-only changes"
    with args.github_output.open("a", encoding="utf-8") as output:
        output.write(f"required={str(required).lower()}\n")
        output.write(f"reason={reason}\n")
    print(f"full_system_required={str(required).lower()}")
    print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
