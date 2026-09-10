## Summary

- 

## Contributor Attestation

- [ ] Every non-merge commit in this pull request has a valid `Signed-off-by:`
  trailer from `git commit -s`.
- [ ] I have the right to submit this change under the Apache License 2.0 and
  have preserved any required third-party notices.

## Validation

- [ ] `python -m ruff check src tests`
- [ ] `python -m mypy --strict src`
- [ ] `python -m pytest -q`
- [ ] Docker/docs validation if applicable
- [ ] Local `tests/tools/merge_gate.py local` report generated for the final commit

## Release Impact

- [ ] None
- [ ] Patch
- [ ] Minor
- [ ] Major
- [ ] Prerelease

## Rollback

Describe the revert or hotfix path.

## Release Signal

- [ ] Normal 45-day train
- [ ] Apply `release:now`
- [ ] Apply `security`
