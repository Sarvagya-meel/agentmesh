from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_PATTERN = re.compile(r'^version = "(?P<version>\d+\.\d+\.\d+)"$', re.MULTILINE)
TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
CONVENTIONAL_TYPE = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?(?P<breaking>!)?:")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
        if match is None:
            raise ValueError(f"Invalid semantic version: {value}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def bump(self, impact: str) -> Version:
        if impact == "major":
            return Version(self.major + 1, 0, 0)
        if impact == "minor":
            return Version(self.major, self.minor + 1, 0)
        if impact == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError(f"Unknown release impact: {impact}")


def release_impact(messages: Sequence[str]) -> str | None:
    impact: str | None = None
    for message in messages:
        first_line = message.splitlines()[0] if message.splitlines() else ""
        match = CONVENTIONAL_TYPE.match(first_line)
        breaking = bool(match and match.group("breaking")) or "BREAKING CHANGE:" in message
        if breaking:
            return "major"
        commit_type = match.group("type") if match else ""
        if commit_type == "feat":
            impact = "minor"
        elif commit_type in {"fix", "perf"} and impact is None:
            impact = "patch"
    return impact


def calculate_next_version(
    latest_version: Version,
    project_version: Version,
    messages: Sequence[str],
) -> tuple[Version | None, str | None]:
    impact = release_impact(messages)
    if impact is None:
        return (project_version if project_version > latest_version else None), None
    effective_impact = "minor" if impact == "major" and latest_version.major == 0 else impact
    candidate = latest_version.bump(effective_impact)
    return max(candidate, project_version), effective_impact


def release_due(last_release: datetime, now: datetime, days: int = 45) -> bool:
    return now - last_release >= timedelta(days=days)


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{completed.stdout}")
    return completed.stdout.strip()


def latest_stable_tag(ref: str) -> str:
    tags = git("tag", "--merged", ref, "--list", "v[0-9]*", "--sort=-version:refname")
    for tag in tags.splitlines():
        if TAG_PATTERN.fullmatch(tag):
            return tag
    raise RuntimeError(f"No stable semantic-version tag is reachable from {ref}")


def project_version(path: Path | None = None) -> Version:
    selected = path or ROOT / "pyproject.toml"
    match = VERSION_PATTERN.search(selected.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Project version not found in {selected}")
    return Version.parse(match.group("version"))


def commit_messages(base_ref: str, head_ref: str) -> list[str]:
    output = git("log", f"{base_ref}..{head_ref}", "--format=%B%x1e")
    return [message.strip() for message in output.split("\x1e") if message.strip()]


def tag_datetime(tag: str) -> datetime:
    value = git("log", "-1", "--format=%cI", tag)
    return datetime.fromisoformat(value)


def evaluate_release(
    *,
    base_ref: str,
    head_ref: str,
    early: bool,
    force: bool,
    now: datetime | None = None,
) -> dict[str, str | bool | None]:
    tag = latest_stable_tag(base_ref)
    messages = commit_messages(tag, head_ref)
    version, impact = calculate_next_version(Version.parse(tag), project_version(), messages)
    due = release_due(tag_datetime(tag), now or datetime.now(UTC))
    should_release = version is not None and (force or early or due)
    if force:
        reason = "manual"
    elif early:
        reason = "release-signal"
    elif due:
        reason = "45-day-train"
    else:
        reason = "not-due"
    return {
        "should_release": should_release,
        "latest_tag": tag,
        "next_version": str(version) if version else None,
        "release_branch": f"release/v{version}" if version else None,
        "impact": impact,
        "reason": reason,
    }


def prepare_release(version: str, *, released_on: date | None = None) -> None:
    parsed = Version.parse(version)
    pyproject = ROOT / "pyproject.toml"
    pyproject_text = pyproject.read_text(encoding="utf-8")
    updated = VERSION_PATTERN.sub(f'version = "{parsed}"', pyproject_text, count=1)
    pyproject.write_text(updated, encoding="utf-8")

    changelog = ROOT / "CHANGELOG.md"
    changelog_text = changelog.read_text(encoding="utf-8")
    marker = "## Unreleased"
    if marker not in changelog_text:
        raise ValueError("CHANGELOG.md does not contain an Unreleased section")
    marker_start = changelog_text.index(marker)
    next_release = re.search(r"^## v\d+\.\d+\.\d+", changelog_text, re.MULTILINE)
    split_at = next_release.start() if next_release else len(changelog_text)
    unreleased = changelog_text[marker_start + len(marker) : split_at]
    prefix = changelog_text[:marker_start]
    suffix = changelog_text[split_at:]
    release_date = (released_on or datetime.now(UTC).date()).isoformat()
    new_text = (
        f"{prefix}{marker}\n\n"
        f"## v{parsed} - {release_date}{unreleased.rstrip()}\n\n"
        f"{suffix.lstrip()}"
    )
    changelog.write_text(new_text.rstrip() + "\n", encoding="utf-8")


def write_github_output(path: Path, values: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if value is None:
                rendered = ""
            elif isinstance(value, bool):
                rendered = str(value).lower()
            else:
                rendered = value
            handle.write(f"{key}={rendered}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate and prepare AgentMesh releases")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--base-ref", default="origin/main")
    evaluate.add_argument("--head-ref", default="origin/develop")
    evaluate.add_argument("--early", action="store_true")
    evaluate.add_argument("--force", action="store_true")
    evaluate.add_argument("--github-output", type=Path)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--version", required=True)

    args = parser.parse_args(argv)
    if args.command == "evaluate":
        result = evaluate_release(
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            early=args.early,
            force=args.force,
        )
        print(json.dumps(result, indent=2))
        if args.github_output:
            write_github_output(args.github_output, result)
        return 0
    prepare_release(args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
