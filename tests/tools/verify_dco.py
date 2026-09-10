from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIGNED_OFF_BY = re.compile(
    r"^Signed-off-by:\s+[^<>\r\n]+\s+<[^<>\s]+@[^<>\s]+>$", re.IGNORECASE
)


def dco_error(message: str) -> str | None:
    """Return the DCO validation error for a commit message, if any."""
    lines = message.rstrip().splitlines()
    footer_start = len(lines)
    while footer_start > 0 and lines[footer_start - 1].strip():
        footer_start -= 1
    if footer_start == 0:
        if not any(line.lower().startswith("signed-off-by:") for line in lines):
            return "DCO sign-off is required; commit with 'git commit -s'"
        return "DCO sign-off must be in a footer separated from the commit subject"

    footer = lines[footer_start:]
    if any(SIGNED_OFF_BY.fullmatch(line.strip()) for line in footer):
        return None
    if any(line.lower().startswith("signed-off-by:") for line in footer):
        return "DCO Signed-off-by trailer must use 'Name <email@example.com>'"
    return "DCO sign-off is required; commit with 'git commit -s'"


def dco_errors_for_messages(messages: Mapping[str, str]) -> list[str]:
    """Return formatted DCO errors for commit messages keyed by commit ID."""
    return [
        f"{commit}: {error}"
        for commit, message in messages.items()
        if (error := dco_error(message)) is not None
    ]


def commit_messages(base: str, head: str) -> dict[str, str]:
    """Read each non-merge commit introduced between two Git revisions."""
    commit_ids = subprocess.check_output(
        ["git", "rev-list", "--no-merges", f"{base}..{head}"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {
        commit: subprocess.check_output(
            ["git", "show", "-s", "--format=%B", commit], cwd=ROOT, text=True
        )
        for commit in commit_ids
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for DCO validation."""
    parser = argparse.ArgumentParser(description="Validate AgentMesh DCO sign-offs")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--message-file", type=Path)
    source.add_argument("--base")
    parser.add_argument("--head")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one commit message or every non-merge commit in a revision range."""
    args = build_parser().parse_args(argv)
    if args.message_file is not None:
        messages = {str(args.message_file): args.message_file.read_text(encoding="utf-8")}
    else:
        if args.head is None:
            raise SystemExit("--head is required when --base is provided")
        messages = commit_messages(args.base, args.head)

    errors = dco_errors_for_messages(messages)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
