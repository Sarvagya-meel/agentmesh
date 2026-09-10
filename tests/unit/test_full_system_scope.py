from tests.tools.full_system_scope import is_non_functional, requires_full_system


def test_documentation_and_repository_metadata_skip_full_system() -> None:
    paths = [
        "README.md",
        "docs/project/release-management.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "NOTICE",
    ]

    assert all(is_non_functional(path) for path in paths)
    assert requires_full_system(paths) is False


def test_functional_paths_require_full_system() -> None:
    paths = [
        "src/agentmesh/config.py",
        "tests/unit/test_config.py",
        "deployment/docker/compose.yml",
        ".github/workflows/quality.yml",
        "pyproject.toml",
    ]

    assert all(not is_non_functional(path) for path in paths)
    assert all(requires_full_system([path]) for path in paths)


def test_empty_change_set_fails_safe_to_full_system() -> None:
    assert requires_full_system([]) is True
