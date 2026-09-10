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


def test_release_pr_dco_starts_at_accepted_develop_head() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert 'dco_base="origin/$BASE_REF"' in workflow
    assert '"$HEAD_REF" == release/*' in workflow
    assert 'dco_base="origin/develop"' in workflow
    assert '--base "$dco_base" --head "$HEAD_SHA"' in workflow


def test_non_functional_changes_skip_expensive_full_system_steps() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "Classify full-system scope" in workflow
    assert "tests/tools/full_system_scope.py" in workflow
    assert "steps.scope.outputs.required == 'true'" in workflow
    assert 'not applicable: $SCOPE_REASON' in workflow
