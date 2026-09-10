from __future__ import annotations

import tomllib
from pathlib import Path

from tests.tools import verify_dco
from tests.tools.verify_dco import dco_error, dco_errors_for_messages

ROOT = Path(__file__).resolve().parents[2]


def test_dco_accepts_a_valid_footer_trailer() -> None:
    message = "feat: add DCO validation\n\nSigned-off-by: Sarvagya Meel <sarvagya@example.com>\n"

    assert dco_error(message) is None


def test_dco_rejects_missing_and_malformed_trailers() -> None:
    assert "required" in (dco_error("feat: add DCO validation\n") or "")
    assert "Name <email" in (
        dco_error("feat: add DCO validation\n\nSigned-off-by: Sarvagya\n") or ""
    )
    assert "footer" in (
        dco_error("feat: add DCO validation\nSigned-off-by: Sarvagya Meel <sarvagya@example.com>\n")
        or ""
    )


def test_dco_reports_each_noncompliant_commit() -> None:
    errors = dco_errors_for_messages(
        {
            "valid": (
                "fix: preserve policy\n\n"
                "Signed-off-by: Sarvagya Meel <sarvagya@example.com>\n"
            ),
            "missing": "fix: missing sign-off\n",
        }
    )

    assert errors == ["missing: DCO sign-off is required; commit with 'git commit -s'"]


def test_release_range_excludes_history_from_both_protected_branches(
    monkeypatch,
) -> None:
    monkeypatch.setattr(verify_dco, "is_ancestor", lambda _ref, _head: True)

    assert verify_dco.revision_args("origin/develop", "release-head") == [
        "git",
        "rev-list",
        "--no-merges",
        "release-head",
        "^origin/develop",
        "^origin/main",
    ]


def test_package_declares_and_includes_apache_license_files() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["license"] == {"text": "Apache-2.0"}
    assert project["tool"]["setuptools"]["license-files"] == ["LICENSE", "NOTICE"]
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "NOTICE").is_file()
