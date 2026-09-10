# AgentMesh

[![quality](https://github.com/Sarvagya-meel/agentmesh/actions/workflows/quality.yml/badge.svg)](https://github.com/Sarvagya-meel/agentmesh/actions/workflows/quality.yml)
[![system-sanity](https://github.com/Sarvagya-meel/agentmesh/actions/workflows/system-sanity.yml/badge.svg)](https://github.com/Sarvagya-meel/agentmesh/actions/workflows/system-sanity.yml)

AgentMesh is a durable, local-first multi-agent runtime for job-search automation
and future agentic workflows.

It separates planning, dispatch, worker execution, retries, event history, and UI
inspection into explicit services so workflows can be replayed, audited, and
recovered instead of disappearing into in-memory agent state.

> Authentication is deferred. Published ports are for local development or
> trusted networks only; do not expose this stack directly to the public internet.

## Why It Exists

Most agent demos are easy to start and hard to trust. AgentMesh is built around
production-shaped constraints from the beginning:

- Durable event history: workflow state is projected from append-only events.
- Explicit service boundaries: agents do not call each other directly.
- Controlled orchestration: the supervisor plans; the control plane validates,
  queues, dispatches, leases, retries, and records.
- Local-first operation: Docker Compose runs the full stack for development.
- Interview-ready architecture: tradeoffs are written down in `plan.md` and
  `docs/`.

## Architecture At A Glance

```text
Streamlit UI
  |-- direct agent test ---------> worker /invoke
  |-- durable direct request ----> control plane queue ---> worker /invoke
  `-- supervised workflow ------> control plane queue ---> supervisor
                                                        |-> LiteLLM Gateway
                                                        `-> workers

PostgreSQL stores:
  agent registry rows, resources, audit events, workflow events, queue claims,
  retries, dead letters, UAT cases, and checkpoint mappings.
```

Core rule:

```text
Every durable request and workflow event passes through the control plane.
Workers receive only the immutable manifest planned and authorized for their step.
```

## Repository Layout

```text
agentmesh/
|-- src/agentmesh/              Python package: agents, services, core models
|-- tests/                      Unit, API, and live/UAT-oriented tests
|-- deployment/                 Docker, Postgres DDLs, and deployment boundaries
|-- docs/                       Runtime, operations, project, IDE, and planning docs
|-- scripts/                    Local launch and Docker operation helpers
|-- tests/tools/                Smoke, sanity, graph, and eval runners
|-- plan.md                     Authoritative runtime architecture contract
|-- AGENTS.md                   AI assistant and repository guidance
`-- pyproject.toml              Dependency groups, tooling, and package metadata
```

For the full documentation map, start with [`docs/README.md`](docs/README.md).

## Quick Start

Python 3.11 or newer and pip 25.1 or newer are required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade "pip>=25.1"
python -m pip install -e . --group local
$env:PYTHONPATH = "src"
python scripts/run_local.py
```

## Docker Workflow

Use the component manager for local stack operations:

```powershell
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service all
pwsh -File scripts\docker_component_manager.ps1 -Action health
pwsh -File scripts\docker_component_manager.ps1 -Action logs -Service all
pwsh -File scripts\docker_component_manager.ps1 -Action stop -Service all
```

The helper detects `COMPOSE_PROFILES`, starts the matching service set, waits for
health checks, and keeps rebuild/restart behavior consistent. See
[`docs/operations/docker.md`](docs/operations/docker.md) for the complete
runbook.

## Runtime Contracts

- Streamlit is a thin client. It never imports a database driver, receives
  `DATABASE_URL`, or writes workflow events.
- The control plane owns registry, queue claims, dispatch, deterministic
  validation, retries, dead letters, events, and projections.
- The supervisor owns planning, semantic review, replan decisions, final summary,
  and LangGraph checkpoint-aware reasoning.
- Workers expose synchronous `/invoke`, execute only the supplied manifest, and
  return structured output to the control plane.
- LiteLLM Gateway is required only for supervisor model calls; worker model
  configuration stays owned by each worker runtime.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\mypy.exe --strict src
.\.venv\Scripts\python.exe tests\tools\clear_langsmith_traces.py
.\.venv\Scripts\python.exe tests\tools\system_sanity.py
$env:COMPOSE_PROFILES = "combined"
docker compose --env-file .env -f deployment/docker/compose.yml config --quiet
$env:COMPOSE_PROFILES = "split"
docker compose --env-file .env -f deployment/docker/compose.yml config --quiet
Remove-Item Env:COMPOSE_PROFILES
```

Generated validation evidence belongs under ignored `outputs/` directories and
is not tracked in Git.

## Documentation

- [`plan.md`](plan.md): authoritative architecture and implementation contract.
- [`docs/runtime/overview.md`](docs/runtime/overview.md): runtime summary.
- [`docs/runtime/functional.md`](docs/runtime/functional.md): behavior and flows.
- [`docs/runtime/non-functional.md`](docs/runtime/non-functional.md): reliability,
  recovery, security, determinism, and operability.
- [`docs/runtime/roadmap.md`](docs/runtime/roadmap.md): runtime delivery roadmap.
- [`docs/operations/docker.md`](docs/operations/docker.md): local Docker runbook.
- [`docs/project/`](docs/project/): product, tech, testing, architecture, and
  coding standards shared across IDEs.

## Current Status

The active implementation is the Python package under `src/agentmesh/`, with
PostgreSQL-backed control-plane services, independent supervisor and worker
processes, Streamlit UI surfaces, Docker Compose deployment, and pytest/ruff/mypy
validation.
