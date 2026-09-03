# Branch Gap and Repository Cleanup Plan

## Scope

Baseline: `feature/Supervisor&RegistryPro` at `032f49c3`.

This report was generated after `git fetch --all --prune --tags` on 2026-09-02.
Each local and `origin` branch was compared with the baseline using ancestry,
`git rev-list --left-right --count`, branch-only commits, and tree/path diffs.
Counts below are `baseline-only / branch-only`. Local and remote references are
grouped when they point to the same commit.

## Executive Summary

- Ten local branches and seven remote branches are fully contained in the
  baseline. They have no commits or files missing from the baseline and can be
  deleted after this report is reviewed.
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
