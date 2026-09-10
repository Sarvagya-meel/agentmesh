# Contributing To AgentMesh

Thanks for helping improve AgentMesh. This repository is maintained as a public,
release-oriented project with `develop` as the source of truth for accepted work
and `main` as the stable release branch.

## Branch Flow

```text
feature/* or fix/* -> pull request -> develop
develop -> release/vX.Y.Z -> pull request -> main -> tag -> GitHub Release
```

- Do not delete `develop`.
- Do not commit directly to `main`.
- Prefer pull requests into `develop` for all normal work.
- Use `release/vX.Y.Z` branches only for release stabilization.
- Use `hotfix/vX.Y.Z` branches only when a released version must be patched.

## Commit Messages

Use Conventional Commits:

```text
feat: add a user-visible capability
fix: repair a bug
docs: update documentation only
test: add or repair tests
ci: update automation
chore: maintain repository metadata or tooling
refactor: change structure without changing behavior
```

Use `BREAKING CHANGE:` in the commit body for incompatible public behavior.

## Pull Requests

Keep one pull request focused on one logical change. Each PR should include:

- Summary of what changed.
- Validation commands or checks run.
- Release impact: none, patch, minor, major, or prerelease.
- Rollback plan.

## Validation

Use the smallest useful validation for the change. For code changes, prefer:

```powershell
python -m ruff check src tests
python -m mypy --strict src
python -m pytest -q
```

For Docker or release changes, also run the relevant Docker compose checks from
`README.md` and `docs/operations/docker.md`.

Generated evidence belongs under ignored `outputs/` directories and should not
be committed.

## AI Assistant Rules

Codex, Copilot, Claude, Kiro, and other assistants must read `AGENTS.md` before
planning edits. Keep changes scoped, preserve user work, and follow the branch
flow above unless Sarvagya explicitly says otherwise.
