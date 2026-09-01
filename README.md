# AgentMesh

AgentMesh is a durable multi-agent runtime. FastAPI agent processes register with a
durable registry/control-plane service, PostgreSQL stores workflow state and queues,
and Streamlit stays a thin client. The UI never creates agents, runs workers, or
writes workflow events.

> Authentication is deferred. Published ports are for local development or trusted
> networks only; do not expose this stack directly to the public internet.

## Architecture

```text
Streamlit
  |-- Agent Playground direct --> ready API/combined agent --> /invoke
  |-- Agent Playground async --> control plane queue --> worker /invoke manifest
  `-- Workflow Playground ----> control plane queue --> supervisor service
                                                   |--> worker /invoke manifest
                                                   `--> workflow.result to user

agentmesh_agents       stable Agent Card identity and compatibility
agentmesh_resources    one row per runtime instance and other platform resource
agentmesh_events       append-only workflow, planning, dispatch, and result timeline
agentmesh_event_claims renewable control-plane leases, retries, and dead letters
LangGraph tables       checkpoint IDs mapped to workflow checkpoints by control plane
```

All durable direct and workflow requests enter the control plane asynchronously. The
orchestrator is an independent supervisor service that polls and claims planning,
validation, replan, and summary actions. LiteLLM Gateway is required only for
supervisor model calls; worker model configuration remains owned by each worker.

Workers expose synchronous `/invoke` and receive immutable per-step input manifests.
Sequential and parallel dependencies are linked by `workflow_id`, `plan_version`,
stable `step_id`, and named input bindings. The supervisor may inspect all authorized
workflow outputs, but it must plan exactly which fields each downstream worker sees.

## Repository Layout

```text
agentmesh/
|-- deployment/
|   |-- docker/             Compose and selective service/agent images
|   |-- postgres/           Idempotent DDLs and migration runner
|   `-- agentcore/          Future managed-runtime adapter boundary
|-- docs/                   Active operating and business documentation
|-- scripts/                Local launch, smoke, and graph-export helpers
|-- src/agentmesh/
|   |-- agents/             Concrete agents and shared runtime primitives
|   |-- core/               Models, providers, persistence, and observability
|   |-- mcp_servers/        Reserved MCP adapter packages
|   `-- services/           Control plane and Streamlit UI
|-- tests/
`-- pyproject.toml          Single dependency source of truth
```

## Install Locally

Python 3.11 or newer and pip 25.1 or newer are required for dependency groups.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade "pip>=25.1"
python -m pip install -e . --group local
$env:PYTHONPATH = "src"
python scripts/run_local.py
```

`pyproject.toml` owns the install sets:

- `control-plane`: FastAPI registry/control plane, PostgreSQL, and queue ownership
- `agent-langgraph`: selective Copilot runtime
- `agent-adk`: selective Google ADK runtime
- `ui`: thin Streamlit service
- `local`: all runtime and development dependencies

## Docker Quick Start

The easiest way to manage the stack is using the PowerShell helper scripts:

```powershell
# Start all services (postgres, migrate, control plane, supervisor, agents, streamlit)
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service all

# Check health
pwsh -File scripts\docker_component_manager.ps1 -Action health

# View logs
pwsh -File scripts\docker_component_manager.ps1 -Action logs -Service all

# Stop all services
pwsh -File scripts\docker_component_manager.ps1 -Action stop -Service all
```

The scripts automatically:
- Detect your `COMPOSE_PROFILES` setting from `.env`
- Apply the correct service set (combined or split profile)
- Rebuild the `migrate` service on each start/restart to apply any new/changed DDLs
- Wait for services to be healthy before returning

See [`docs/docker-operations.md`](docs/docker-operations.md) for the complete runbook.

## Runtime Roles

- `combined`: `/invoke`, health/readiness, Agent Card, and assignment consumption
- `api`: `/invoke`, health/readiness, and Agent Card; never polls assignments
- `worker`: health/readiness and assignment consumption through the synchronous
  worker invoke contract; no public Agent Playground `/invoke` route

Every instance publishes its agent ID, runtime instance ID, role, lifecycle status,
endpoint, active count, start time, last model success, and heartbeat. Direct readiness
requires an `api` or `combined` instance; assignment readiness requires a `worker` or
`combined` instance.

## Agent Playground Contracts

Direct mode waits on the selected agent API and does not create durable workflow
state:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8101/invoke `
  -ContentType "application/json" `
  -Body '{"message":"Make Dubai travel plans","approval_required":false}'
```

Control-plane mode submits durable direct work asynchronously. The control plane
owns queueing, leased dispatch, retries, deterministic validation, and result events:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/workers/langgraph-copilot/assignments `
  -ContentType "application/json" `
  -Body '{"message":"Make Dubai travel plans"}'
```

Normal workflows always enter the control plane first. The supervisor claims
planning actions, can pause on `planning.input_requested` until
`planning.input_provided`, and returns the final `workflow.result` with
`source=supervisor` and `destination=user`. Transient worker failures such as 429,
timeouts, and 502-504 responses are retried by the control plane without disturbing
the supervisor; semantic failures trigger checkpoint review or replan.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\mypy.exe --strict src
$env:COMPOSE_PROFILES = "combined"
docker compose --env-file .env -f deployment/docker/compose.yml config --quiet
$env:COMPOSE_PROFILES = "split"
docker compose --env-file .env -f deployment/docker/compose.yml config --quiet
Remove-Item Env:COMPOSE_PROFILES
```

The active LangGraph delivery status is in
[`src/agentmesh/agents/ROADMAP.md`](src/agentmesh/agents/ROADMAP.md).
The local agent-runtime design is split into
[`functional`](docs/agent-runtime-functional.md) and
[`non-functional`](docs/agent-runtime-non-functional.md) notes, with roadmap
tracking in [`docs/agent-runtime-roadmap.md`](docs/agent-runtime-roadmap.md).
