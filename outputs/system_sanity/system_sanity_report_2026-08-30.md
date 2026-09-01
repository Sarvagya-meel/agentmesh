# AgentMesh System Sanity Report

Run date: 2026-08-30
Workspace: `C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh`

## 1. Scope

Checked Docker build, startup, runtime readiness, registry aggregation, direct agent invocation, orchestrated workflow execution, PostgreSQL event persistence, LangSmith configuration, LangSmith trace visibility, and automated tests.

## 2. Permanent Fixes Applied

### Docker env propagation

Root cause: `deployment/docker/compose.yml` did not pass LangSmith variables from `.env` into the services. The stack could start, but LangSmith tracing relied on container-local defaults instead of the configured project/key.

Fix: added `LANGSMITH_*` and compatibility `LANGCHAIN_*` env passthrough to the shared Compose LLM config.

Changed file:

- `deployment/docker/compose.yml`

### Local LangSmith SDK env propagation

Root cause: app `Settings` read `LANGSMITH_TRACING` and `LANGSMITH_PROJECT`, but not `LANGSMITH_API_KEY` or `LANGSMITH_ENDPOINT`. Local pytest could enable tracing from `.env` while the LangSmith SDK could not see the API key, producing a shutdown-time `401 Unauthorized` ingest warning even though tests passed.

Fix: added explicit `langsmith_endpoint`, `langsmith_api_key`, and `langsmith_workspace_id` settings, then updated `configure_langsmith()` to export all SDK env vars when tracing is enabled and a key is available.

Changed files:

- `src/agentmesh/config.py`
- `src/agentmesh/core/observability.py`
- `tests/unit/test_conversation_agent.py`

### Agent ready aggregation

Previous root cause already fixed in this workstream: registry multi-instance aggregation did not preserve the ready runtime `last_seen`, which could make ready agents appear stale/offline.

Changed files:

- `src/agentmesh/agents/common/resource_repository.py`
- `src/agentmesh/services/service_agentmesh_server/registry/service.py`
- `tests/unit/test_registry_service.py`

## 3. Build And Startup

Command used:

```powershell
docker compose --env-file .\.env -f .\deployment\docker\compose.yml --profile combined up -d --build
```

Result: passed.

Evidence:

- Build/startup log: `outputs/system_sanity/docker_build_startup_after_langsmith_fix_2026-08-30.log`
- Final env recreate log: `outputs/system_sanity/docker_recreate_final_env_2026-08-30.log`

Final containers:

- `agentmesh-postgres`: healthy
- `agentmesh-orchestrator-supervisor`: healthy on `8000`
- `agentmesh-agent-langgraph-copilot-1`: healthy on `8101`
- `agentmesh-agent-googleadk-chatagent-1`: healthy on `8102`
- `agentmesh-streamlit`: up on `8501`

Evidence: `outputs/system_sanity/docker_ps_final_2026-08-30.log`

## 4. Runtime Readiness

HTTP checks passed:

- `GET http://localhost:8000/health` returned `status: ok`
- `GET http://localhost:8101/ready` returned `status: ready`, role `combined`
- `GET http://localhost:8102/ready` returned `status: ready`, role `combined`
- `GET http://localhost:8000/registry/agents` returned all expected agents online

Registry online agents:

- `googleADK-Chatagent`
- `langgraph-copilot`
- `orchestrator-supervisor-agent`

Evidence: `outputs/system_sanity/http_checks_after_fix_2026-08-30.json`

## 5. Direct Agent Smoke

Final direct invokes passed:

- LangGraph endpoint `/invoke`: `COMPLETED`, final reply `LangGraph runtime is ready.`
- Google ADK endpoint `/invoke`: `success`, final reply `ADK runtime is ready.`

Evidence: `outputs/system_sanity/final_direct_invokes_2026-08-30.json`

## 6. Workflow Smoke

Orchestrator workflow smoke passed before the final env recreation:

- Workflow reached `AWAITING_PLAN_APPROVAL`
- Plan approval accepted
- LangGraph task completed
- Agent output approval accepted
- Google ADK task completed
- Workflow reached `COMPLETED`

Persisted workflow events observed in PostgreSQL:

- `WORKFLOW_STARTED`
- `AGENT_SNAPSHOT_CAPTURED`
- `PLAN_CREATED`
- `PLAN_APPROVAL_REQUESTED`
- `PLAN_APPROVED`
- `TASK_ASSIGNED`
- `AGENT_OUTPUT_PROPOSED`
- `AGENT_APPROVAL_REQUESTED`
- `AGENT_OUTPUT_APPROVED`
- `TASK_COMPLETED`
- `WORKFLOW_COMPLETED`

Note: one qualitative issue appeared in the workflow result. ADK answered with a different arithmetic example than LangGraph drafted. This is not an infrastructure failure, but it should become an eval assertion in LangSmith or a deterministic integration test.

## 7. LangSmith

`.env` was used for LangSmith. Secret values are not stored in this report.

Final verified runtime env inside orchestrator, LangGraph, and ADK containers:

- `LANGSMITH_TRACING=true`
- `LANGCHAIN_TRACING_V2=true`
- `LANGSMITH_PROJECT=AgentMesh`
- `LANGCHAIN_PROJECT=AgentMesh`
- `LANGSMITH_API_KEY` present
- `LANGCHAIN_API_KEY` present

LangSmith SDK check:

- API key present: yes
- Endpoint: `https://api.smith.langchain.com`
- Project match: `AgentMesh`
- Recent trace sample: 20 runs found in the last 30 minutes
- Recent run names included `LangGraph`, `load_context`, `classify_task`, `generate_response`, `validate_output`, and `finalize`

Evidence:

- `outputs/system_sanity/container_langsmith_env_final_2026-08-30.log`
- `outputs/system_sanity/langsmith_check_final_2026-08-30.json`

Best-practice basis from LangSmith docs:

- Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and optionally `LANGSMITH_PROJECT`.
- Set `LANGSMITH_ENDPOINT` for the correct hosted region because a mismatched endpoint can cause authentication failure.
- Each service in a distributed app needs its own credentials; trace context does not propagate credentials.

References:

- https://docs.langchain.com/langsmith/observability-quickstart
- https://docs.langchain.com/langsmith/create-account-api-key
- https://docs.langchain.com/langsmith/log-traces-to-project

## 8. Automated Tests

Focused tests after fixes:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_conversation_agent.py tests\unit\test_registry_service.py -q
```

Result: passed.

Full test suite after fixes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result: `81 passed, 1 warning in 14.99s`

The previous local LangSmith `401 Unauthorized` ingest warning disappeared after the config fix.

Evidence:

- `outputs/system_sanity/pytest_focused_after_langsmith_fix_2026-08-30.log`
- `outputs/system_sanity/pytest_full_after_langsmith_fix_2026-08-30.log`

## 9. Logs

Final startup/runtime logs were captured for:

- orchestrator
- LangGraph agent
- Google ADK agent
- PostgreSQL
- Streamlit
- migrate job

Final post-smoke error scan searched for:

```text
ERROR, Traceback, Exception, failed, 401, 403, timeout, refused, 409
```

Result: no matches in final post-smoke logs.

Evidence:

- `outputs/system_sanity/logs_final_post_smoke/`

Earlier workflow run did show repeated `409 Conflict` assignment-claim responses from LangGraph while output approval was pending. The workflow still completed. This is a warning to investigate as queue/lease noise, not a blocker.

## 10. Current Status

Overall status: PASS with two follow-up warnings.

Green:

- Docker build passed
- Docker startup passed
- All required containers running
- Health/readiness endpoints passed
- Registry shows all agents online
- Direct LangGraph invoke passed
- Direct ADK invoke passed
- Workflow smoke passed
- PostgreSQL event persistence observed
- LangSmith project/auth/traces verified
- Full pytest passed

Warnings:

- Assignment worker can repeatedly attempt to claim an already-claimed assignment while approval is pending, producing `409 Conflict` noise in orchestrated workflow logs.
- Workflow semantic consistency needs eval coverage; ADK changed the arithmetic example during the smoke workflow.

## 11. Recommended Next Moves

1. Add automated sanity command that runs Compose config, build, health checks, direct invokes, workflow smoke, DB event checks, log scans, and LangSmith trace checks in one repeatable command.
2. Add LangSmith datasets/evaluators for multi-agent workflow consistency, approval-gate behavior, routing choice, and final answer faithfulness to previous task outputs.
3. Convert the SQLite sanity catalog into executable test metadata or generate pytest/LangSmith eval cases from it.
4. Add CI modes:
   - local: skip LangSmith checks if secrets are absent
   - CI explicit eval job: fail if LangSmith secrets are absent or trace/eval upload fails
5. Investigate the repeated `409 Conflict` claim loop and suppress or prevent duplicate claims while an assignment is already claimed/pending approval.
