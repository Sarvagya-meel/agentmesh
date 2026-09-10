# Release Management

AgentMesh uses `develop` for accepted development and `main` for public,
versioned releases. Every protected-branch change is reviewed through a public
pull request, validated against the exact PR commit, and merged manually by the
repository maintainer.

## Branch Flow

```text
feature/*, fix/*, chore/*, docs/*, test/*, codex/*
    -> PR -> develop
    -> release/vX.Y.Z -> PR -> main
    -> tag vX.Y.Z -> GitHub Release
```

- Preserve `develop`; it is the source of truth for accepted active work.
- Keep `main` stable and release-only.
- Use `release/vX.Y.Z` only for generated release preparation and synchronization.
- Use `hotfix/vX.Y.Z` from `main` for released-version repairs.
- Never rewrite or delete a published version tag.

## Daily Development

Start normal work from the latest `develop`:

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c feature/<short-name>
```

Commit each logical change separately:

```powershell
git add <files>
git commit -m "feat(scope): add capability"
git commit -m "test(scope): cover capability"
git push -u origin HEAD
```

Install the repository hooks once per checkout:

```powershell
pwsh -File scripts/install_git_hooks.ps1
```

The `commit-msg` hook enforces Conventional Commits. The `pre-push` hook rejects
direct pushes to `develop` and `main`, runs the fast local gate, and writes an
ignored report bound to the current commit under `outputs/test-reports/local/`.
Git hooks are a developer convenience; GitHub Actions is the authoritative gate.

Open a PR into `develop`. The PR title must also use Conventional Commit format
because squash merge uses that title as the accepted commit. After the required
check passes and discussions are resolved, the maintainer's GitHub Merge click
is the human approval.

## Merge Gate

The required check is `merge-gate / gate`. It aggregates these suites:

| Suite | Coverage |
| --- | --- |
| `static` | PR metadata, release ancestry, Ruff, mypy, graph exports |
| `unit` | `tests/unit` |
| `integration` | `tests/api` |
| `docker` | Clean Compose build and startup |
| `uat` | Opt-in live tests under `tests/live` |
| `smoke` | Health, registry, workflow, PostgreSQL, and log checks |
| `browser` | Desktop and mobile Streamlit browser checks |
| `llm` | Provider execution and LangSmith evaluation |

Every suite writes compact JSON. The aggregator creates:

```text
outputs/test-reports/<PR-created-YYYY-MM-DD>/pr-<number>/<head-sha>/
  gate-report.json
  gate-report.csv
  gate-report.md
```

The JSON report is authoritative for automation, CSV opens directly in
spreadsheet tools, and Markdown is copied to the Actions summary. Full command
output stays in Actions logs; only consolidated reports are uploaded.

The report schema is versioned and includes `pr_number`, `base_ref`, `head_ref`,
`head_sha`, `tested_sha`, timestamps, suite results, durations, waiver data,
counts, blocking problems, and `overall_status`. The gate rejects missing,
malformed, stale, or non-passing reports with `PR not allowed` annotations.

Reproduce the fast gate locally with:

```powershell
\.venv\Scripts\python.exe tests\tools\merge_gate.py local
```

## Optional Test Policy

`.github/test-policy.yml` is JSON-compatible YAML so the standard-library gate
can parse it without adding a runtime dependency. Every active suite is required
by default and only `pass` is accepted. The initial policy contains a 30-day
waiver for LangSmith quota exhaustion; it expires on 2026-10-10 and must not be
silently extended.

To permit `warn` or `skip`, mark the suite non-required and add a waiver with its
suite, owner, reason, creation date, and expiration date. Temporary waivers
default operationally to 30 days and may not exceed 365 days. A genuinely
permanent optional check must set `expires_on` to `null` and `permanent` to
`true`. Failures and missing results are never waived.

## Versioning And Release Train

The release train evaluates `develop` daily. It opens a release when releasable
changes exist and either 45 days have passed since the latest stable tag or an
early signal exists. Early signals are a breaking Conventional Commit or a
merged PR labeled `release:now` or `security`. A manual workflow dispatch forces
evaluation without bypassing tests or approval.

Version impact is automatic:

| Signal | Version impact |
| --- | --- |
| `feat:` | Minor |
| `fix:` or `perf:` | Patch |
| `!` or `BREAKING CHANGE:` | Minor before 1.0.0, major afterward |
| `docs:`, `test:`, `ci:`, `chore:` | No release by themselves |

The workflow creates or updates one `release/vX.Y.Z` branch, updates
`pyproject.toml` and `CHANGELOG.md`, and opens a PR to `main`. If `develop`
advances, the release branch is synchronized and the old report becomes invalid.
Only `release/*` and `hotfix/*` may target `main`.

After the maintainer merges a passing release PR, automation creates the
immutable tag, publishes GitHub-generated release notes, and opens a PR that
synchronizes the release version and changelog back into `develop`.

## Rollback

For an unreleased regression, use GitHub's revert operation to create a focused
PR into `develop`, run the gate, and merge it normally.

For a released regression:

```powershell
git switch main
git pull --ff-only origin main
git switch -c hotfix/vX.Y.Z
```

Apply the smallest fix, use a `fix:` commit, open a PR to `main`, and publish a
new patch release after the complete gate passes. Merge the hotfix changes back
into `develop` through the synchronization PR. Do not move an existing tag.

See [Merge Gate Troubleshooting](../operations/merge-gate-troubleshooting.md)
for failure diagnosis and recovery.
