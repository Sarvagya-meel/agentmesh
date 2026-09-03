# Branch Gap and Repository Cleanup Plan

## Main Adoption Review: Awaiting Approval

Requested scope: identify useful things in main that the current branch lacks;
record a plan only, and wait for review before importing or implementing anything.
This review supersedes the immediate integration sequence below: selective
adoption comes first, and merging main remains a separate decision.

Comparison refreshed on 2026-09-04: current `feature/Supervisor&RegistryPro`
at `0bac89b5` versus `origin/main` at `fac0c1056b2146865fe02136c439849329960609`.
Local `main` is a different, older tip: it has zero commits absent from HEAD
(`git rev-list --left-right --count HEAD...main` gives `37 / 0`). The source
for the following review is therefore **origin/main**, not local main.

There are no files present only in origin/main. Shared files do differ, but the
review found no must-have runtime capability to import. Most main-side code is
an older implementation replaced by the current control-plane architecture.
This is a source-level assessment, not proof of behavioral equivalence: main
was not deployed or tested independently during this review.

### Candidate Approval List

| ID | Main-only detail and source | Current branch | Recommendation and acceptance check | Decision |
| --- | --- | --- | --- | --- |
| M1 | Editor exclusions for virtual-environment and distribution folders in [origin/main `.vscode/settings.json`](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/.vscode/settings.json). | Hides caches and egg-info, but not `.venv` or distribution folders; retains pytest discovery and source-path configuration. | Optional, low priority: add narrowly scoped `.venv` and generated build/dist exclusions if these folders clutter the Explorer. Do not copy main's file: it has missing commas and an invalid escape, and also hides `__init__.py`. Validate JSON and retain test discovery, source paths, and visibility of source files. | Pending review |
| M2 | Package-level `create_orchestration_checkpointer` export in [origin/main `core/database/__init__.py`, line 8](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/core/database/__init__.py#L8). | Factory still exists in `core/database/checkpoint.py`; package initialization intentionally avoids importing optional LangGraph dependencies into control-plane-only processes. | Defer unless an external caller needs the old package-level import. No repository caller requiring that export was identified. If approved, implement lazy compatibility, not main's eager import; test both the old import with LangGraph installed and core database import without optional framework dependencies. | Pending evidence; recommend defer |

Neither item is required for the current runtime to work. M1 is a small developer
convenience; M2 is compatibility work only, not missing checkpoint functionality.

### Differences Not Recommended for Import

| Main-side behavior and source | Why keep the current implementation |
| --- | --- |
| Combined supervisor/API service in [origin/main Compose](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/deployment/docker/compose.yml) and direct orchestrator dependency in [workflow routes](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/services/service_agentmesh_server/api/routes/workflows.py). | Conflicts with `plan.md`: retain separate control plane, supervisor actions, validated dispatch, and durable state ownership. |
| Direct SQL reads and sleep-driven refresh in [origin/main Streamlit app, line 253](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/services/service_agentmesh_ui/app.py#L253). | Resource/audit views already exist through the current API client. Do not restore UI database coupling, old sidebar navigation, or page-wide polling behavior. |
| Silent missing-key fallback in [origin/main ADK factory test, line 32](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/tests/unit/test_google_adk_agent.py#L32) and canned success in [ADK agent, line 71](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/agents/agent_adk_spark/agent.py#L71). | Current factory retains explicit `LLM_PROVIDER=mock` selection and validates configured real-provider credentials. Do not disguise missing credentials as successful model execution. |
| Older approval, task-prompt, and checkpoint paths in [origin/main ConversationAgent](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/agents/agent_langgraph_copilot/agent.py). | Current branch adds explicit rejection coverage, validated dependency inputs, and expanded checkpoint handling. Main is not a source of additional reject/revise/recovery features. |
| Queued-direct approval disabled in [origin/main WorkerService](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/services/service_agentmesh_server/workers/service.py). | Preserve current request-controlled approval policy; importing this default would undo requested human-approval behavior. |
| Start-with-build and non-destructive rebuild defaults in [origin/main Docker helper](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/scripts/docker_component_manager.ps1). | These differ from the user's current start/restart/rebuild contract. Do not copy older operations code or its runbook claims. |
| Smaller tracing setup in [origin/main observability module](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/src/agentmesh/core/observability.py). | Current branch adds tracing configuration, identity metadata, redaction, and failure isolation. Main's simpler code is not an observability gap to fill. |
| LiteLLM dependency under the LangGraph group in [origin/main pyproject.toml, line 22](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/pyproject.toml#L22). | The same `1.97.0` pin exists here under the current dependency grouping. There is no missing package version to carry across. |
| Expanded inline IDE architecture guidance in [origin/main architecture instructions](https://github.com/Sarvagya-meel/agentmesh/blob/fac0c1056b2146865fe02136c439849329960609/.github/instructions/Architecture.md.instructions.md). | Current `AGENTS.md`, `plan.md`, and focused docs replace duplicated guidance. Older text assigns durable dispatch to the supervisor and would reintroduce conflicting instructions. |

### Plan After Review

1. Review M1 and M2 independently; approving the plan does not imply importing
   every difference or merging main wholesale.
2. Implement only approved items on the current architecture, one scoped change
   at a time. Recheck source SHAs before using this list if either branch moves.
3. Run each item's acceptance checks and inspect the diff. For M2, also run
   checkpoint-focused tests and control-plane import checks in its lean environment.
4. Present the completed diff before the separate main-integration decision.
   Keep the known 69 merge conflicts and stale graph-export CI failure as
   integration work, not features to copy from main.

G1 (Streamlit telemetry) and G2 (IDE onboarding) below come from **other
branches**, not main. They remain separate backlog items and are not evidence of
missing main functionality. No runtime, configuration, or test files were changed
for this review; only this plan was updated.

## Execution and PR Readiness: 2026-09-04

Refreshed origin before cleanup. Reviewed `feature/Supervisor&RegistryPro` at
`0bac89b5` against `origin/main` at `fac0c105`. The sections below this update
retain the original September 2 comparison and proposed dispositions.

### Completed Cleanup

Deleted these ten local branches after verifying each tip was an ancestor of HEAD:

- `agents/plan-revision-assistance`
- `codex/repo-cleanup-phase-1`
- `copilot-setup`
- `copilot/first_agent`
- `copilot/orchestrator_agent`
- `feature/db_postgress`
- `feature/langSmithObsEval`
- `feature/PlanAndDocumentationAlignment`
- `LangGraphAgent`
- `LangGraphAgentPro`

Deleted the seven corresponding origin branches, excluding the three local-only
names `agents/plan-revision-assistance`, `codex/repo-cleanup-phase-1`, and
`feature/db_postgress`. Remote deletion was atomic, guarded by expected tip SHAs,
and followed verification that all seven tips were ancestors of the retained
`origin/feature/Supervisor&RegistryPro` branch.

Retained local and remote `main`, the current feature branch, the unique local
`agents/understanding-hooks-and-kiro-files` documentation branch, and both
foreign-history prototype references. The prototype references duplicate each
other but contain content absent from the baseline; their archival review is
still pending. No main branch was merged, reset, or force-pushed.

### Merge Blockers

`git rev-list --left-right --count origin/main...HEAD` reports one main-only
commit and 38 feature-only commits. Direct tree comparison reports 345 changed
files, 43,028 insertions, and 1,872 deletions.

The non-mutating `git merge-tree --write-tree --name-only origin/main HEAD`
check exits with conflicts in 69 paths: 37 under `src`, seven under `tests`,
eight under `.github`, three under `.kiro`, four under `deployment`, four under
`docs`, two under `scripts`, and one each in `.env.example`, `.vscode`,
`pyproject.toml`, and `README.md`. Many runtime conflicts are add/add conflicts
against main's snapshot commit. An absence of main-only file paths does not
prove semantic equivalence or make this merge automatically safe.

Local validation using `.venv/Scripts/python.exe`:

- `-m pytest -q`: 143 passed, two deprecation warnings.
- `-m ruff check src tests`: passed.
- `-m mypy --strict src`: passed across 96 source files.
- `scripts/export_langgraph_mermaid.py --check`: failed because
  `orchestrator-supervisor.mmd` is stale. This is a configured CI gate.
- LangSmith trace delivery reported HTTP 429 for the monthly trace quota;
  this did not fail pytest but external trace validation remains limited.

These checks validate the current feature tree, not a resolved merge tree.
Docker and browser UAT were not rerun for this branch audit. GitHub CLI is not
installed, so hosted PR checks and branch protection were not inspected.

### Integration Plan

1. Create an isolated `codex/` integration branch/worktree from the feature tip
   and merge `origin/main` there, leaving the presentation checkout unchanged.
2. Resolve conflicts individually against `plan.md` and the active runtime
   docs. Review main's snapshot changes for intent; do not blanket-select one
   side for runtime, deployment, dependency, or test conflicts.
3. Regenerate and review the stale supervisor graph export using the repository
   export script. Address G1 and G2 separately if included in the PR scope.
4. Rerun all four CI checks on the resolved tree, then Docker smoke and browser
   UAT for API/queue execution, approval/reject/revise, dependencies, retries,
   replay, and checkpoint recovery.
5. Open or update the PR to main, verify hosted checks and protection, and merge
   only after review. Realign local main afterward without discarding unique work.

No merge or PR creation was performed in this audit. Runtime code, deployment
configuration, and active architecture docs were intentionally left unchanged.

## Scope

Baseline: `feature/Supervisor&RegistryPro` at `032f49c3`.

This report was generated after `git fetch --all --prune --tags` on 2026-09-02.
Each local and `origin` branch was compared with the baseline using ancestry,
`git rev-list --left-right --count`, branch-only commits, and tree/path diffs.
Counts below are `baseline-only / branch-only`. Local and remote references are
grouped when they point to the same commit.

## Executive Summary

- Ten local branches and seven remote branches are ancestors of the baseline.
  They have no unmerged commits; historical file snapshots may still differ.
  Their deletion was completed as recorded in the September 4 update above.
- `agents/understanding-hooks-and-kiro-files` has one branch-only documentation
  commit. Its `.kiro/README-IDE.md` is not in the baseline, but much of it is
  stale or duplicates the repository-wide `AGENTS.md` contract.
- `origin/main` has one divergent snapshot commit, but it has no path that is
  absent from the baseline. The baseline has 273 paths not present in
  `origin/main` and modifies 71 shared paths, so `origin/main` should be updated
  through a normal merge/PR rather than cherry-picking its snapshot commit.
- `origin/feature/LiteLLM` and `origin/feature/agentInDocker` point to the same
  commit and have no merge base with this repository history. Their inherited
  history is from a different project. Their two AgentMesh prototype commits
  are superseded by the current runtime, except for one useful Streamlit
  telemetry setting that should be considered separately.

## Branch Comparison

| Branch reference | Tip | Difference | What exists there but not in the baseline | Disposition |
| --- | --- | ---: | --- | --- |
| `agents/plan-revision-assistance` | `9fdd9ea886` | `37 / 0` | Nothing; tip is an ancestor of the baseline. | Delete locally. |
| `agents/understanding-hooks-and-kiro-files` | `2ff348dbc0` | `37 / 1` | `.kiro/README-IDE.md` from commit `2ff348db`. | Review and rewrite useful onboarding content; do not merge verbatim. |
| `codex/repo-cleanup-phase-1` | `207b15f6ad` | `13 / 0` | Nothing; tip is an ancestor and its upstream is already deleted. | Delete locally. |
| `copilot-setup`, `origin/copilot-setup` | `8bac62b2fe` | `35 / 0` | Nothing; tip is an ancestor. | Delete locally and on origin. |
| `copilot/first_agent`, `origin/copilot/first_agent` | `a944b3cb5c` | `33 / 0` | Nothing; tip is an ancestor. | Delete locally and on origin. |
| `copilot/orchestrator_agent`, `origin/copilot/orchestrator_agent` | `a944b3cb5c` | `33 / 0` | Nothing; same ancestor tip as `copilot/first_agent`. | Delete locally and on origin. |
| `feature/db_postgress` | `5f74d8bf67` | `24 / 0` | Nothing; tip is an ancestor and its upstream is already deleted. | Delete locally. |
| `feature/langSmithObsEval`, `origin/feature/langSmithObsEval` | `a193c37bc0` | `7 / 0` | Nothing; tip is an ancestor. | Delete locally and on origin. |
| `feature/PlanAndDocumentationAlignment`, `origin/feature/PlanAndDocumentationAlignment` | `9dfc952431` | `6 / 0` | Nothing; tip is an ancestor. | Delete locally and on origin. |
| `LangGraphAgent`, `origin/LangGraphAgent` | `2df6033bcb` | `14 / 0` | Nothing; tip is an ancestor. | Delete locally and on origin. |
| `LangGraphAgentPro`, `origin/LangGraphAgentPro` | `40dee8a97b` | `12 / 0` | Nothing; tip is an ancestor. | Delete locally and on origin. |
| local `main` | `6663b78c2a` | `36 / 0` | Nothing; local tip is an ancestor of the baseline, but it is `ahead 1, behind 1` relative to `origin/main`. | Keep and realign after the baseline is merged. |
| `origin/main` | `fac0c1056b` | `37 / 1` | One snapshot commit, `fac0c105` (`LangGraphAgentPro`). No file path exists only on this branch. | Keep; merge the baseline through the normal PR path. |
| `origin/feature/LiteLLM` | `63981cd5a4` | no merge base | Same foreign-history tree as `origin/feature/agentInDocker`; includes two AgentMesh prototype commits and `.streamlit/config.toml`. | Delete this duplicate remote name after retaining an archive reference. |
| `origin/feature/agentInDocker` | `63981cd5a4` | no merge base | Same content as `origin/feature/LiteLLM`; 5,516 paths exist only in that unrelated tree. | Keep temporarily as the archive pointer, then delete after prototype review. |

## Gap Plan

### G1. Carry Forward the Streamlit Telemetry Setting

Evidence: `origin/feature/LiteLLM` and `origin/feature/agentInDocker` contain
`.streamlit/config.toml` with `browser.gatherUsageStats = false`; the baseline
does not contain that setting.

Plan:

1. Add the setting through the current Streamlit configuration boundary, either
   as `.streamlit/config.toml` in the UI image or as the equivalent Compose
   environment value.
2. Add a Docker smoke assertion that the Streamlit health endpoint responds and
   startup logs do not announce usage-statistics collection.
3. Keep this as a small baseline-native change; do not cherry-pick either
   foreign-history branch.

### G2. Replace the Stale IDE Guide With Current Onboarding

Evidence: local branch `agents/understanding-hooks-and-kiro-files`, commit
`2ff348db`, adds `.kiro/README-IDE.md` only.

Plan:

1. Extract only still-valid hook discovery and invocation guidance.
2. Put concise Kiro-specific notes in `.kiro/README.md` or the active operations
   documentation and point to `AGENTS.md` for repository-wide rules.
3. Exclude stale references to `mcp/memory-server`, placeholder VS Code tasks,
   and duplicated architecture/coding rules.
4. Delete the source branch after the rewritten guidance is committed.

### G3. Reconcile `origin/main` Without Backporting Its Snapshot

Evidence: `origin/main` has branch-only commit `fac0c105`, while the baseline has
37 branch-only commits. A direct tree comparison finds zero paths unique to
`origin/main`, 273 paths unique to the baseline, and 71 modified shared paths.

Plan:

1. Open or update the PR from `feature/Supervisor&RegistryPro` to `main`.
2. Resolve conflicts in favor of current active architecture and docs, reviewing
   the 71 shared paths rather than cherry-picking `fac0c105`.
3. Run the full test, lint, type-check, Docker smoke, and Streamlit UAT gates.
4. After merge, reset the local `main` reference to the updated `origin/main`.

### G4. Archive the Foreign-History Runtime Prototype

Evidence: `origin/feature/LiteLLM` and `origin/feature/agentInDocker` both point
to `63981cd5` and have no merge base with the baseline. Their inherited 1,030
commits and 5,516 branch-only paths belong primarily to another repository.
Their AgentMesh-specific commits are `e9ae734f` and `63981cd5`.

Prototype-to-current mapping:

| Prototype capability | Prototype branch path | Current baseline replacement |
| --- | --- | --- |
| Registry and task storage | `agent_runtime/registry/main.py` | `src/agentmesh/services/service_agentmesh_server/registry/` and PostgreSQL repositories |
| Orchestration | `agent_runtime/orchestrator/main.py` | control plane, independent supervisor, durable dispatch, and event sourcing |
| LangGraph and ADK workers | `agent_runtime/*_agent/main.py` | `src/agentmesh/agents/agent_langgraph_copilot/` and `agent_adk_spark/` |
| Streamlit playground | `agent_runtime/streamlit_ui/app.py` | `src/agentmesh/services/service_agentmesh_ui/` |
| Local Compose topology | `docker-compose.local-agents.yml` | `deployment/docker/compose.yml` |
| Sanity catalog | `scripts/build_sanity_catalog.py` and SQLite output | DDL `008_agentmesh_uat_cases.sql`, `sanity_catalog.py`, and `system_sanity.py` |

The prototype SQLite fallback is intentionally not a gap because the active
architecture requires durable control-plane state in PostgreSQL.

Plan:

1. Create an archive tag or bundle for commit `63981cd5` if historical retention
   is required.
2. Delete the duplicate `origin/feature/LiteLLM` reference immediately after the
   archive reference exists.
3. Complete G1, then delete `origin/feature/agentInDocker` as well.
4. Never merge either branch wholesale because their histories are unrelated.

## Repository Cleanup List

### Safe to Delete Locally

All commits on these branches are reachable from the baseline:

- `agents/plan-revision-assistance`
- `codex/repo-cleanup-phase-1`
- `copilot-setup`
- `copilot/first_agent`
- `copilot/orchestrator_agent`
- `feature/db_postgress`
- `feature/langSmithObsEval`
- `feature/PlanAndDocumentationAlignment`
- `LangGraphAgent`
- `LangGraphAgentPro`

### Safe to Delete on Origin

These remote tips are reachable from `origin/feature/Supervisor&RegistryPro`:

- `copilot-setup`
- `copilot/first_agent`
- `copilot/orchestrator_agent`
- `feature/langSmithObsEval`
- `feature/PlanAndDocumentationAlignment`
- `LangGraphAgent`
- `LangGraphAgentPro`

The following is also safe to delete as a duplicate pointer after an archive
reference is retained:

- `feature/LiteLLM` (exactly duplicates `feature/agentInDocker` at `63981cd5`)

### Review Before Deleting

- Local `agents/understanding-hooks-and-kiro-files`: preserve or rewrite its one
  useful documentation delta first.
- Remote `feature/agentInDocker`: retain temporarily as the prototype archive,
  complete G1, then delete.

### Keep

- `feature/Supervisor&RegistryPro` and
  `origin/feature/Supervisor&RegistryPro`: current baseline.
- local `main` and `origin/main`: primary integration branch; realign local
  `main` after the feature branch is merged.

## Cleanup Verification

Before deleting refs, rerun:

```powershell
git fetch --all --prune
git branch --merged 'feature/Supervisor&RegistryPro'
git rev-list --left-right --count 'feature/Supervisor&RegistryPro...<branch>'
```

After cleanup, verify that only the baseline, `main`, and explicitly retained
review/archive refs remain with `git branch -a -vv`.
