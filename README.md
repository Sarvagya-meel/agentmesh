# AgentMesh

AgentMesh is a durable multi-agent runtime. FastAPI agent processes register with a
control plane, PostgreSQL stores assignments and workflow history, and Streamlit stays
a thin client. The UI never creates agents, runs workers, or writes workflow events.

> Authentication is deferred. Published ports are for local development or trusted
> networks only; do not expose this stack directly to the public internet.

## Architecture

```text
Streamlit
  |-- Direct --> ready API/combined agent --> shared agent executor
  `-- Queued --> control plane --> PostgreSQL assignment --> worker/combined agent
                                      |
                                      `--> result event --> supervisor LangGraph

agentmesh_agents       stable Agent Card identity and compatibility
agentmesh_resources    one row per runtime instance and other platform resource
agentmesh_events       append-only workflow and task timeline
agentmesh_event_claims renewable assignment leases, retries, and dead letters
LangGraph tables       checkpoints, pending interrupts, replay, and Store memory
```

Each process creates exactly one concrete agent and one concurrency-limited executor.
Direct HTTP requests and queued assignments share that executor in `combined` mode.
Executions with the same `thread_id` are serialized; unrelated threads can overlap.

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

- `control-plane`: FastAPI supervisor, PostgreSQL, and LangGraph
- `agent-langgraph`: selective Copilot runtime
- `agent-adk`: selective Google ADK runtime
- `ui`: thin Streamlit service
- `local`: all runtime and development dependencies

## Docker Quick Start

The easiest way to manage the stack is using the PowerShell helper scripts:

```powershell
# Start all services (postgres, migrate, orchestrator, agents, streamlit)
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

## Docker Quick Start

Copy `.env.example` to the ignored `.env` file and set `COMPOSE_PROFILES`:

```dotenv
COMPOSE_PROFILES=combined
```

The easiest way to manage the stack is using the PowerShell helper scripts:

```powershell
# Start all services (postgres, migrate, orchestrator, agents, streamlit)
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service all

# The migrate service rebuilds on each start to apply any new/changed DDLs
# It only applies new or modified DDLs (idempotent - checksum tracked)
# Orchestrator waits for migrate to complete before starting
```

See [`docs/docker-operations.md`](docs/docker-operations.md) for:
- Complete runbook with health checks, logs, and troubleshooting
- Direct Docker Compose commands for advanced use
- Split profile configuration and scaling

**Note:** The `migrate` service runs once and exits. When you run `start` or `restart`:
- It rebuilds to pick up any new/changed DDL files
- It applies only new or changed DDLs (checksum-tracked and idempotent)
- It exits with status 0 after completion

## Runtime Roles

- `combined`: `/invoke`, health/readiness, Agent Card, and assignment consumption
- `api`: `/invoke`, health/readiness, and Agent Card; never polls assignments
- `worker`: health/readiness and assignment consumption; never exposes `/invoke`

Every instance publishes its agent ID, runtime instance ID, role, lifecycle status,
endpoint, active count, start time, last model success, and heartbeat. Direct readiness
requires an `api` or `combined` instance; assignment readiness requires a `worker` or
`combined` instance.

## Agent Playground Contracts

Direct mode waits on the selected agent API:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8101/invoke `
  -ContentType "application/json" `
  -Body '{"message":"Make Dubai travel plans","approval_required":false}'
```

Queued mode creates a directed assignment through the control plane and follows its
PostgreSQL event timeline:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/workers/langgraph-copilot/assignments `
  -ContentType "application/json" `
  -Body '{"message":"Make Dubai travel plans"}'
```

Normal workflows always use supervisor planning, plan approval, directed assignment,
worker leasing, and a separate agent-output approval when policy requires it.

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
