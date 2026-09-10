# AgentMesh Full-System Testing Steps

Use this runbook to validate AgentMesh from a clean Docker state. Run all
commands from the repository root in PowerShell. Generated logs belong under
`outputs/full_scale_testing/`, which is intentionally ignored by Git.

## Prerequisites

- Docker Desktop is running.
- `.env` contains the required local provider and database settings.
- `.venv` exists with the project development dependencies installed.
- Ports `4000`, `5432`, `8000`, `8101`, `8102`, `8110`, and `8501` are free.

Never print `.env` or provider secrets into test logs. Validate only non-secret
settings such as backend names, provider names, and environment mode.

## 1. Create the Log Directory

```powershell
New-Item -ItemType Directory -Force outputs/full_scale_testing/clean_run
```

## 2. Remove the Existing AgentMesh Stack

This deletes AgentMesh containers, Compose-built images, networks, and the
PostgreSQL data volume. It permanently removes local workflow history.

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml --profile combined down --volumes --rmi all --remove-orphans 2>&1 |
  Tee-Object outputs/full_scale_testing/clean_run/01-cleanup.log
```

Confirm that the project has no remaining Compose images or volumes:

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml --profile combined images
docker volume ls --filter label=com.docker.compose.project=agentmesh
```

The cleanup is project-scoped. Do not remove unrelated Docker projects.

## 3. Build Every Image from Scratch

`--pull --no-cache` verifies Dockerfiles and dependency installation without
reusing previous application layers.

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml --profile combined build --pull --no-cache 2>&1 |
  Tee-Object outputs/full_scale_testing/clean_run/02-build.log
```

## 4. Start the Runtime

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml --profile combined up -d --wait --force-recreate 2>&1 |
  Tee-Object outputs/full_scale_testing/clean_run/03-startup.log

docker compose --env-file .env -f deployment/docker/compose.yml --profile combined ps
```

Expected long-running services are PostgreSQL, LiteLLM, control plane,
supervisor, LangGraph worker, Google ADK worker, and Streamlit. The migration
container is expected to exit successfully after applying the schema.

## 5. Validate Health and Configuration

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8110/health
Invoke-WebRequest http://127.0.0.1:8101/health
Invoke-WebRequest http://127.0.0.1:8102/health
Invoke-WebRequest http://127.0.0.1:4000/health/liveliness
Invoke-WebRequest http://127.0.0.1:8501/_stcore/health
```

Verify runtime configuration inside the control-plane image without displaying
secret values:

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml exec -T control-plane `
  python -c "from agentmesh.core.config import get_settings; s = get_settings(); print({'app_env': s.app_env, 'registry_backend': s.registry_backend, 'event_store_backend': s.event_store_backend, 'provider': s.llm_provider})"
```

## 6. Run Local Quality Checks

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy --strict src
```

## 7. Run System Sanity and Live UAT

The sanity tool checks Compose, health, registry discovery, both direct agent
invocations, a complete workflow, PostgreSQL events, logs, and LangSmith.

```powershell
.venv\Scripts\python.exe tests\tools\system_sanity.py --no-build `
  --output-dir outputs\full_scale_testing\clean_run\system_sanity

$env:AGENTMESH_LIVE_UAT = "1"
.venv\Scripts\python.exe -m pytest tests/live/test_demo_uat.py -q
Remove-Item Env:AGENTMESH_LIVE_UAT
```

Classify provider `429` responses and LangSmith quota failures as external
dependency failures only after confirming the event stream records retries and
the terminal state correctly. Rerun the affected live test after the provider
window resets; do not conceal the original failure.

## 8. Test Streamlit in a Browser

Open `http://127.0.0.1:8501` and verify these flows:

1. Registry: connect to `http://control-plane:8000`, refresh, and confirm the
   required workers are online.
2. Agent Playground, Direct API Request: send an exact-response prompt to each
   available framework and confirm the response renders.
3. Agent Playground, Control Plane Request: submit a message and confirm the
   queued run reaches `COMPLETED`, displays a result, and shows its event trail.
4. Workflow Playground: start a workflow with human approval, approve the plan,
   approve or revise the agent output, and confirm `WORKFLOW_COMPLETED`.
5. Open existing: load the workflow ID and confirm its persisted plan, result,
   status, and events are restored.
6. Recovery controls: load checkpoints, investigate without side effects, then
   exercise workflow rerun, task rerun, and recover-latest through live UAT.

## 9. Capture and Review Runtime Logs

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml --profile combined logs --no-color --timestamps 2>&1 |
  Tee-Object outputs/full_scale_testing/clean_run/runtime-final.log

Select-String -Path outputs/full_scale_testing/clean_run/runtime-final.log `
  -Pattern "Traceback|ERROR|FAILED|429|quota" -CaseSensitive:$false
```

For each match, record the service, workflow or task ID, retry count, terminal
event, and whether the cause is local or external.

## Verified Run: 2026-09-07

- Clean Compose deletion removed all AgentMesh containers, images, and volumes.
- All seven application images rebuilt with `--pull --no-cache`.
- All expected long-running containers started healthy on a new database.
- Pytest: `163 passed, 11 skipped, 1 warning`.
- Ruff: passed.
- Strict mypy: passed for 91 source files.
- System sanity: all runtime and database assertions passed. LangSmith trace
  verification failed because the external monthly trace quota was exhausted.
- Live UAT: `11 passed` in 137.50 seconds on the final clean stack.
- Browser: registry, direct ADK request, control-plane request, persisted
  workflow loading, and the approval workflow all completed successfully.

Testing exposed and fixed two package-cleanup regressions:

- `Dockerfile.agent` still copied the removed `src/agentmesh/config.py` file.
- Importing the core PostgreSQL repository eagerly imported the optional
  LangGraph checkpoint dependency into the control-plane image.
