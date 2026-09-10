from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_sync_uses_protected_auto_merge() -> None:
    workflow = (ROOT / ".github/workflows/publish-release.yml").read_text(
        encoding="utf-8"
    )

    assert 'gh pr merge "$number" --repo "$GITHUB_REPOSITORY" --auto --squash' in workflow
    assert "--admin" not in workflow
    assert "git push origin develop" not in workflow


def test_release_sync_inherits_the_protected_main_gate() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert 'git merge-base --is-ancestor "$HEAD_SHA" origin/main' in workflow
    assert "Full testing is inherited from the protected main promotion." in workflow
    assert "Verify released commit and authorize synchronization" in workflow
