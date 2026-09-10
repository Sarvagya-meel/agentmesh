from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.tools import release_train
from tests.tools.release_train import (
    Version,
    calculate_next_version,
    release_due,
    release_impact,
)


def test_release_impact_uses_highest_conventional_commit_signal() -> None:
    assert release_impact(["fix: one", "feat(api): two"]) == "minor"
    assert release_impact(["feat!: replace API"]) == "major"
    assert release_impact(["docs: explain flow"]) is None


def test_breaking_change_before_one_zero_increments_minor() -> None:
    version, impact = calculate_next_version(
        Version.parse("0.3.2"), Version.parse("0.3.2"), ["feat!: replace API"]
    )
    assert version == Version.parse("0.4.0")
    assert impact == "minor"


def test_release_candidate_never_moves_behind_project_version() -> None:
    version, impact = calculate_next_version(
        Version.parse("0.0.1"), Version.parse("0.1.0"), ["fix: repair queue"]
    )
    assert version == Version.parse("0.1.0")
    assert impact == "patch"


def test_non_release_commits_do_not_bump_current_version() -> None:
    version, impact = calculate_next_version(
        Version.parse("1.2.3"), Version.parse("1.2.3"), ["docs: update guide"]
    )
    assert version is None
    assert impact is None


def test_release_train_is_due_after_45_days() -> None:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    assert release_due(now - timedelta(days=45), now)
    assert not release_due(now - timedelta(days=44), now)


def test_prepare_release_updates_version_and_moves_unreleased_notes(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n### Added\n\n- Gate.\n\n"
        "## v0.0.1 - 2026-08-22\n\n- Initial.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_train, "ROOT", tmp_path)

    release_train.prepare_release("0.2.0", released_on=datetime(2026, 9, 10).date())

    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert "## Unreleased\n\n## v0.2.0 - 2026-09-10" in changelog
    assert "### Added\n\n- Gate." in changelog
