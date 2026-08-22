# Agent LangGraph Copilot

The LangGraph Copilot is an independently deployable AgentMesh worker for chat,
drafting, and review tasks. It can execute directly over HTTP or consume assignments
from the AgentMesh control plane.

## Responsibilities

- validate and classify assigned work
- create a small execution outline for multi-step requests
- generate and validate a model response
- pause for output approval when the task policy requires it
- resume from the same LangGraph thread after approve, revise, or reject
- publish an Agent Card and runtime-instance heartbeat in `combined` or `worker` mode
- renew an assignment lease during long-running work
- preserve retry attempts and dead-letter exhausted assignments

The agent does not own workflow planning, cross-agent routing, or workflow-plan
approval. Those remain responsibilities of the orchestrator supervisor.

## Task Classification

Tasks are classified as `simple` or `multi_step` based on keywords in the user request.
Multi-step tasks trigger a planning phase that creates an execution outline before
response generation.

Multi-step keywords: `plan`, `compare`, `research`, `design`, `strategy`, `evaluate`, `analyze`

## Runtime Lifecycle

The worker registers before accepting assignments and moves through `STARTING`,
`READY`, `DEGRADED`, `DRAINING`, and `OFFLINE`. Its heartbeat is sent every 60 seconds;
the registry marks an instance stale after 180 seconds without a successful update.
Normal heartbeats update presence without adding audit events. Registration, recovery,
degradation, stale detection, and shutdown remain visible transitions.

Each assignment is claimed with a renewable lease and a stable idempotency key. A
transient failure is scheduled for another attempt with backoff. Exhausted or permanent
failures are dead-lettered instead of being retried forever.

Each process creates one agent and one shared executor. `combined` mode serves direct
requests and consumes assignments through that executor. `api` serves direct requests
only, while `worker` consumes assignments and deliberately has no `/invoke` route.
The executor bounds process concurrency and serializes calls sharing a `thread_id`.

## Graph

```text
validate_input -> load_context -> classify_task
                                  | simple     -> generate_response
                                  | multi_step -> plan_task -> generate_response

generate_response -> validate_output -> evaluate_output
                                      | no approval -> finalize
                                      | approval    -> human_approval

human_approval -> approve -> finalize
               -> revise  -> generate_response
               -> reject  -> reject
```

`generate_response` has a bounded LangGraph retry policy for model-provider errors.
Approval uses LangGraph `interrupt()` and resumes with `Command(resume=...)`.

## Agent Card

Routable capabilities describe work the planner may assign:

- `CHAT`
- `DRAFT`
- `REVIEW`

Runtime features are metadata rather than routable capabilities:

```json
{
  "framework": "langgraph",
  "human_in_loop": true,
  "approval_modes": ["output_review"],
  "supports_resume": true
}
```

## HTTP API

- `GET /health`: process liveness
- `GET /ready`: dependency and worker readiness
- `GET /agent-card`: current registration metadata
- `POST /invoke`: direct invocation
- `POST /conversations/{thread_id}/resume`: resume output approval
- `GET /conversations/{thread_id}/checkpoints`: list checkpoint history
- `POST /conversations/{thread_id}/replay`: replay from a checkpoint
- `POST /conversations/{thread_id}/fork`: create an isolated checkpoint fork
- `GET /graph/mermaid`: return the offline-renderable graph source

Direct invocation is automatic unless `approval_required` is true. Orchestrated
tasks require output approval by default and use a stable thread derived from the
workflow and task IDs.

## Configuration

- `AGENT_ENDPOINT`: public endpoint recorded in the registry
- `AGENT_RUNTIME_ROLE`: `combined`, `api`, or `worker`
- `AGENT_MAX_CONCURRENCY`: maximum executions in one process
- `LANGGRAPH_CHECKPOINT_BACKEND`: `memory` or `postgres`
- `LANGGRAPH_STORE_BACKEND`: `memory` or `postgres`
- `LANGGRAPH_LONG_TERM_MEMORY_ENABLED`: enable explicit opt-in user memory
- `LANGGRAPH_MEMORY_RETENTION_DAYS`: memory expiration period
- `LANGSMITH_TRACING`: disabled by default; opt in to external traces
- `DATABASE_URL`: PostgreSQL connection used for checkpoints and audit resources
- `AGENTMESH_API_URL`: control-plane URL
- `WORKER_HEARTBEAT_SECONDS`: registry heartbeat interval
- `POLL_INTERVAL_SECONDS`: assignment poll interval
- `LLM_PROVIDER`: `mock` or `groq`
- `GROQ_API_KEY`: model credential for Groq mode

## Run Locally

```powershell
$env:PYTHONPATH = "src"
python -m uvicorn agentmesh.agents.agent_langgraph_copilot.app:app `
  --host 127.0.0.1 --port 8101
```

```powershell
Invoke-RestMethod http://localhost:8101/health
Invoke-RestMethod http://localhost:8101/agent-card
Invoke-RestMethod -Method Post -Uri http://localhost:8101/invoke `
  -ContentType "application/json" `
  -Body '{"message":"Make Dubai travel plans","approval_required":true}'
```

## Run With Docker

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml `
  up -d --build agent-langgraph-copilot
```

The selective image contains `core`, `agents/common`, and this agent package. It
does not copy the UI, control-plane service, ADK agent, or future MCP servers.

## Verification

```powershell
python -m pytest tests/unit/test_conversation_agent.py tests/api/test_agent_runtime.py -q
python -m ruff check src tests
python -m mypy --strict src
python scripts/export_langgraph_mermaid.py --check
```

See [LEARNING.md](LEARNING.md) for the decisions, alternatives, and tradeoffs behind
the implementation.
