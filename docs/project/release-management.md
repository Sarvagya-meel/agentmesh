# Release Management

AgentMesh uses a release-train model that keeps active development and public
release presentation separate.

## Branches

```text
feature/* or fix/* -> PR -> develop
develop -> release/vX.Y.Z -> PR -> main
main -> tag vX.Y.Z -> GitHub Release
```

- `develop` is the source of truth for accepted active work. Do not delete it.
- `main` is the public stable release branch.
- `feature/*`, `fix/*`, and `codex/*` branches are short-lived work branches.
- `release/vX.Y.Z` branches are cut from `develop` and receive only release
  stabilization changes.
- `hotfix/vX.Y.Z` branches are cut from `main` for urgent released-version fixes
  and then merged back into `develop`.

## Versioning

Use Semantic Versioning:

- `MAJOR`: incompatible public behavior after `v1.0.0`.
- `MINOR`: user-visible features or meaningful runtime capability changes.
- `PATCH`: backwards-compatible fixes.
- `-alpha.N`, `-beta.N`, or `-rc.N`: prerelease validation builds.

Before `v1.0.0`, AgentMesh may still change public contracts, but release notes
must call out migration or compatibility impact.

## Commit And Release Mapping

Conventional Commits drive the default release impact:

| Commit type | Release impact |
| --- | --- |
| `feat:` | Minor |
| `fix:` | Patch |
| `docs:`, `test:`, `ci:`, `chore:` | No version bump unless release-facing |
| `BREAKING CHANGE:` | Major after `v1.0.0`; explicit migration note before `v1.0.0` |

## Release Checklist

1. Confirm `develop` is green.
2. Create `release/vX.Y.Z` from `develop`.
3. Update `pyproject.toml` version if needed.
4. Update `CHANGELOG.md`.
5. Run code, documentation, and Docker validation.
6. Open a PR from `release/vX.Y.Z` to `main`.
7. Merge after public review and green checks.
8. Tag `main` with `vX.Y.Z`.
9. Publish the GitHub Release from that tag.
10. Merge release changes back into `develop` if the release branch received
    stabilization commits.

## Release Validation Gate

Release PRs into `main` must prove the tested commit matches the branch being
released.

- The release branch must contain the latest `origin/develop` commit.
- Quality CI must pass for the release PR head.
- System sanity must pass for the release PR head.
- LangSmith trace-shape validation must pass when the release PR targets `main`.
- The GitHub Actions summary should show the compact sanity report, not full raw
  logs.
- Raw logs and JSON evidence may be uploaded as artifacts, but the PR-facing
  report should be human-readable and machine-readable.

The system sanity workflow writes:

- `system_sanity_report.md` for the PR summary.
- `system_sanity_report.json` for automation.
- `system_sanity_report.csv` for spreadsheet review.
- `system_sanity_summary.json` for full structured details.

If the release branch does not include the latest `origin/develop`, the release
gate fails and the branch must be updated before review continues.

## Rollbacks

If unreleased work breaks `develop`, revert the PR on `develop` and continue
from a new fix branch.

If a public release breaks `main`, create a `hotfix/vX.Y.Z` branch from `main`,
patch the issue, open a PR to `main`, tag the patch release, publish the GitHub
Release, and merge the hotfix back into `develop`.

Do not rewrite public release tags. Publish a new patch release instead.

## GitHub Rulesets

Protect `develop`, `main`, and `release/*` with:

- Require pull request before merge.
- Require status checks before merge.
- Require conversation resolution.
- Block force pushes.
- Restrict deletions.
- Allow admins to bypass only for emergency recovery.

`main` should stay release-only so visitors, installers, and release archives see
the most stable version of AgentMesh.
