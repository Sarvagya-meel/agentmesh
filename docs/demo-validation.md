# Demo Validation

The repeatable acceptance suite has three layers:

- Ordinary pytest: deterministic unit/API coverage for approval, dependency
  context, leases, retry/dead-letter behavior, validation, replay, and recovery.
- Opt-in `tests/live/test_demo_uat.py`: real Docker HTTP execution, including
  Streamlit AppTest connect/navigation/disconnect and direct approval/reject/revise;
  queued approval/reject/revise; both workers with approval disabled; workflow
  approval, read-only checkpoint replay, recovery, and workflow/task reruns.
- `scripts/browser_smoke.cjs`: the Docker-served Streamlit pages in a real browser
  at 1440x1000 and 390x844, with screenshots and JavaScript error checks.

The live suite calls the configured provider and can consume API quota. Ordinary
pytest skips it unless `AGENTMESH_LIVE_UAT=1` is explicitly set. Retry fault
injection remains deterministic unit/API coverage; live tests do not deliberately
crash workers or exhaust provider quotas. This is bounded acceptance coverage,
not a claim that every possible user workflow or failure mode is tested.

## Repeat From Scratch

Use the repository virtual environment and install the `local` dependency group.
Browser checks additionally require Node, Playwright, and Chromium (or Microsoft
Edge on Windows). `PLAYWRIGHT_MODULE` may point to an existing Playwright package;
otherwise normal Node module resolution is used.

Back up PostgreSQL before running this destructive command. The runner verifies
the Compose project name, then removes AgentMesh containers, locally built images,
and the AgentMesh PostgreSQL volume before each round. Other projects and global
Docker builder caches are not pruned. Each application image is rebuilt with
`--no-cache --pull`, and migrations run against a fresh database.

```powershell
.\.venv\Scripts\python.exe scripts/demo_verify.py --reset-data --rounds 2
```

Pass `--node <absolute-node-executable>` when Node is not on PATH. Each round runs
Ruff, strict uncached mypy, graph-export checks, cache-cleared pytest, fresh Docker
build/startup, the live suite, system sanity, and browser smoke. Evidence is saved
under ignored `outputs/system_sanity/demo_final/round1` and `round2`.
`summary.json` records exit codes. A failed check stays failed in the report;
provider/trace quota failures are not converted into passes.

To rerun only live acceptance without destroying data:

```powershell
$env:AGENTMESH_LIVE_UAT = '1'
.\.venv\Scripts\python.exe -m pytest tests/live -q
Remove-Item Env:AGENTMESH_LIVE_UAT
```

PostgreSQL migration `009_live_uat_automation.sql` attaches the executable test
file to the relevant existing UAT catalog IDs without replacing their expected
behavior. The original migration `008` remains unchanged. These metadata links
identify coverage, not permission to execute arbitrary database command strings.

## Merge Preparation

`codex/main-demo-readiness` includes `origin/main` through a reviewed merge commit.
The conflicting snapshot content was retained from the current architecture as
documented in `gap.md`. Main was not rewritten. Additional readiness fixes make
reruns return a new durable child ID, preserve approval policy, and reject explicit
terminal-checkpoint recovery before creating child events. The stale supervisor
graph export was regenerated, and in-process tests no longer inherit trace enablement.

Fresh-start validation also exposed concurrent LangGraph schema setup between the
supervisor and workers. Native checkpoint/store migrations now share a
database-scoped advisory lock; dedicated lock sessions close on success or failure.
The local dependency group includes the same LiteLLM adapter used by ADK, so a
clean CI install can collect and run the ADK tests without relying on old packages.

Re-fetch main and verify its ancestry before opening the PR. Hosted CI and
GitHub's mergeability status must be checked separately from local acceptance.
