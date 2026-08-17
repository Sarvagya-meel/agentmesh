# Docker Log Audit and Remediation Action Plan

Date: 2026-08-17

## Executive summary

A full review of the current Docker container logs shows that the stack is currently healthy and free of runtime error signatures. The recent issues that were observed during validation were caused by configuration and network misalignment rather than a persistent application fault in the containers themselves.

Current status:
- PostgreSQL: healthy, no error-level entries
- Migrate job: completed successfully, no error-level entries
- Orchestrator: healthy, no error-level entries
- LangGraph agent: healthy, no error-level entries
- Google ADK agent: healthy, no error-level entries
- Streamlit UI: healthy, no error-level entries

## Container-by-container audit

| Container | Status | Recent log findings | Severity |
| --- | --- | --- | --- |
| `agentmesh-postgres` | Healthy | No error-level entries. Database initialized normally and continued serving requests. | None |
| `agentmesh-migrate` | Healthy | DDL migration scripts were skipped because the schema already existed; no failure. | None |
| `agentmesh-orchestrator-supervisor` | Healthy | Requests are succeeding; no exception tracebacks or failed startup. | None |
| `agentmesh-agent-langgraph-copilot` | Healthy | Only health check traffic observed; no error-level entries. | None |
| `agentmesh-agent-googleadk-chatagent` | Healthy | Previously showed a Groq invalid-key failure during `/invoke`; currently clean after configuration fix. | Resolved |
| `agentmesh-streamlit` | Healthy | No error-level entries; UI started normally. | None |

## Issues identified and severity

### Critical: invalid Groq credentials causing ADK runtime failure

Observed issue:
- `/invoke` on the Google ADK worker returned `500 Internal Server Error`.
- The log stack trace showed: `litellm.BadRequestError: GroqException - Invalid API Key`.

Impact:
- The worker could not complete LLM calls.
- Direct runtime requests failed even though the container was up.

Fix applied:
- Verified valid `GROQ_API_KEY` in the project `.env`.
- Ensured the current Docker config uses the live env values.
- Restarted the affected service with the corrected environment.

Status: Resolved

### High: default runtime configuration was effectively assuming Groq when no key existed

Observed issue:
- The app defaulted to a Groq-oriented flow while the environment lacked a valid key.
- This caused runtime logic to fail without a graceful fallback.

Impact:
- New local environments could crash or misbehave without an explicit key.
- The stack was not resilient to blank or absent credentials.

Fix applied:
- Added graceful fallback behavior for local mock mode when Groq is unavailable.
- Set the default provider configuration to a non-blocking local mode for development.
- Kept Groq enabled only when the real key is present.

Status: Resolved

### High: orchestrator requests failed when using Docker-internal service hostnames from the host machine

Observed issue:
- Requests to `http://orchestrator-supervisor-agent:8000/...` are valid only inside the Docker network.
- From a browser or host machine, this hostname does not resolve the same way.
- This made it look like the orchestrator had an availability problem.

Impact:
- False 503/service-level failures when testing from outside the compose network.

Fix applied:
- Validated the correct endpoint is `http://localhost:8000/...` from the host.
- Restarted the orchestration service with the live env config.
- Confirmed `/workflows/start` succeeds from the host machine.

Status: Resolved

### Medium: missing operational guardrails for environment-driven container startup

Observed issue:
- The project allowed a blank or invalid Groq env path to reach runtime without explicit user-facing fallback guidance.
- There was no clear separation between host-targeted URLs and container-targeted internal URLs in the runbook.

Impact:
- Operational confusion during setup and restart.
- Risk of future runtime regressions during environment changes.

Action plan:
- Add startup validation for required env keys in Groq mode.
- Document that `localhost` is the host endpoint and Docker names are only for inter-container communication.
- Add a quick health smoke script to every compose cycle.

Status: Planned

## Corrective action plan by severity

### P1 — Critical / immediate

1. Continue validating `GROQ_API_KEY` before any production or staging startup.
2. Fail fast with a clear message if Groq mode is selected without a key.
3. Keep infra restart steps explicit and environment-aware.
4. Validate the ADK `/invoke` route after each deployment using a smoke check.

Owner: platform / ops
Target: immediate

### P2 — High / next deployment cycle

1. Standardize the default LLM mode to a safe local fallback (`mock`) unless an explicit Groq key is present.
2. Add a consistent provider-fallback policy across orchestrator, worker agents, and all runtime factories.
3. Add host-vs-container URL guidance to the deployment docs.
4. Add a compose smoke check for workflow startup and agent health endpoints.

Owner: engineering
Target: next patch / next release

### P3 — Medium / follow-up

1. Add a `docker-compose` smoke test script under `scripts/` for automated health checks.
2. Capture the service startup order and dependency rules in deployment documentation.
3. Add a short note about `localhost` vs service-name endpoint semantics.

Owner: devops / docs
Target: next maintenance cycle

### P4 — Low / hygiene

1. Increase log visibility for startup and health checks in the compose stack.
2. Add explicit warnings when the stack is running in mock mode instead of Groq mode.
3. Keep a concise troubleshooting note in the repo docs for reproducible local debugging.

Owner: engineering
Target: backlog

## Verified end-state

The current stack is operating cleanly after remediation:
- Control plane responds on `http://localhost:8000/health`
- Workflow creation succeeds through `http://localhost:8000/workflows/start`
- Worker health checks succeed on `http://localhost:8101/health` and `http://localhost:8102/health`
- Streamlit responds on `http://localhost:8501`

No active fatal errors remain in the current container logs.

## Recommended next step

Keep the stack in Groq mode only when a valid key is present in the root `.env`, and continue using `localhost` endpoints for host-side testing. Treat Docker service names like `orchestrator-supervisor-agent` as internal-only network addresses.
