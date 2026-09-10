from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def find_bash() -> str | None:
    candidates = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists() and "system32" not in candidate.lower():
            return candidate
    return None


BASH = find_bash()


@pytest.mark.skipif(BASH is None, reason="bash is required to execute repository Git hooks")
def test_commit_message_hook_accepts_and_rejects_messages(tmp_path: Path) -> None:
    message = tmp_path / "message.txt"
    message.write_text("feat(hooks): validate commits\n", encoding="utf-8")
    accepted = subprocess.run(
        [BASH, ".githooks/commit-msg", str(message).replace("\\", "/")],
        cwd=ROOT,
        check=False,
    )
    message.write_text("unclear message\n", encoding="utf-8")
    rejected = subprocess.run(
        [BASH, ".githooks/commit-msg", str(message).replace("\\", "/")],
        cwd=ROOT,
        check=False,
    )

    assert accepted.returncode == 0
    assert rejected.returncode == 1


@pytest.mark.skipif(BASH is None, reason="bash is required to execute repository Git hooks")
def test_pre_push_hook_rejects_direct_develop_push() -> None:
    update = (
        "refs/heads/develop "
        "1111111111111111111111111111111111111111 "
        "refs/heads/develop "
        "2222222222222222222222222222222222222222\n"
    )
    completed = subprocess.run(
        [BASH, ".githooks/pre-push", "origin", "https://example.invalid/repo.git"],
        cwd=ROOT,
        input=update,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 1
    assert "direct pushes" in completed.stdout
