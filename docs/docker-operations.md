# Docker Operations

Run commands from the repository root. Copy `.env.example` to `.env`, keep credentials
only in the ignored `.env`, and choose exactly one Compose profile through
`COMPOSE_PROFILES`. Do not add a second profile with the `--profile` flag.

> Internal control-plane routes use `INTERNAL_SERVICE_TOKEN`. Public agent and UI ports
> remain local-development surfaces and should not be exposed directly to the internet.

## Quick Start

The easiest way to manage the stack is using the PowerShell helper scripts in `scripts/`:

```powershell
# Start all services (postgres, migrate, control plane, supervisor, agents, streamlit)
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service all

# Check health of all endpoints
pwsh -File scripts\docker_component_manager.ps1 -Action health

# View logs for all services
pwsh -File scripts\docker_component_manager.ps1 -Action logs -Service all

# Stop all services
pwsh -File scripts\docker_component_manager.ps1 -Action stop -Service all

# Restart a specific service (e.g., migrate rebuilds schema with any DDL changes)
pwsh -File scripts\docker_component_manager.ps1 -Action restart -Service migrate
```

The scripts automatically:
- Detect your `COMPOSE_PROFILES` setting from `.env`
- Apply the correct service set (combined or split profile)
- Rebuild the `migrate` service on each start/restart to apply any new/changed DDLs
- Wait for services to be healthy before returning

For the older combined local sequence, use the sequential helper:

```powershell
# Start in order: registry/control plane -> streamlit -> agent(s)
pwsh -File scripts\start_registry_streamlit_agent.ps1
```

## Docker Compose (Base Commands)

For advanced use, you can run Docker Compose commands directly. The helper scripts wrap these:

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml up -d --build
docker compose --env-file .env -f deployment/docker/compose.yml ps
docker compose --env-file .env -f deployment/docker/compose.yml down
docker compose --env-file .env -f deployment/docker/compose.yml logs --tail 100
docker compose --env-file .env -f deployment/docker/compose.yml build
docker compose --env-file .env -f deployment/docker/compose.yml config
```

**Note:** The `migrate` service runs once and exits. When you run `start` or `restart`:
- It rebuilds to pick up any new/changed DDL files
- It applies only new or changed DDLs (idempotent)
- It exits with status 0 after completion
- Runtime services wait for `service_completed_successfully` before starting

## Combined Profile

Combined mode is the simplest local topology. Agent ports are published for direct
host-side testing.

```powershell
docker compose --env-file .env `
  -f deployment/docker/compose.yml up -d --build
docker compose --env-file .env `
  -f deployment/docker/compose.yml ps
```

Host endpoints:

- registry/control plane: `http://localhost:8000`
- supervisor health/checkpoints: `http://localhost:8110`
- LiteLLM proxy: `http://localhost:4000`
- LangGraph Copilot: `http://localhost:8101`
- Google ADK agent: `http://localhost:8102`
- Streamlit: `http://localhost:8501`
- PostgreSQL: `localhost:5432`

Durable direct and workflow requests should be submitted to the control plane. The
supervisor runs as its own service and claims planning, validation, replan, and
summary actions; workers expose synchronous `/invoke` behind the control-plane
dispatch path.

## Split Profile

Split mode runs API and assignment-consumer roles independently from the same image.
Agent API ports are internal so replicas can scale without host-port conflicts. Use
Streamlit, the registry endpoint, or `docker compose exec` for split-mode direct tests.

```powershell
docker compose --env-file .env `
  -f deployment/docker/compose.yml up -d --build `
  --scale agent-langgraph-copilot-api=2 `
  --scale agent-langgraph-copilot-worker=2 `
  --scale agent-googleadk-chatagent-api=2 `
  --scale agent-googleadk-chatagent-worker=2
```

Do not activate both profiles. Stop one topology before switching:

```powershell
docker compose --env-file .env `
  -f deployment/docker/compose.yml down
```

`down` preserves the named PostgreSQL volume unless `--volumes` is explicitly added.

## Health And Logs

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8110/health
Invoke-RestMethod http://localhost:4000/health/liveliness
Invoke-RestMethod http://localhost:8101/ready
Invoke-RestMethod http://localhost:8102/ready

docker compose --env-file .env `
  -f deployment/docker/compose.yml logs --tail 100
docker compose --env-file .env `
  -f deployment/docker/compose.yml logs -f agent-langgraph-copilot
```

The repository helper remains convenient for the combined profile:

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action health
pwsh -File .\scripts\docker_component_manager.ps1 `
  -Action rebuild -Service agent-langgraph-copilot
pwsh -File .\scripts\docker_component_manager.ps1 `
  -Action logs -Service control-plane,supervisor
```

## Migrations

The `migrate` service runs once per container lifecycle. It rebuilds on each `start` or
`restart` to pick up any new/changed DDL files, then applies only the new or modified
migrations (checksum-tracked and idempotent).

```powershell
# Start services including migrate (rebuilds and applies new DDLs if any)
docker compose --env-file .env -f deployment/docker/compose.yml up -d migrate

# Run migration manually (idempotent - skips already applied DDLs)
docker compose --env-file .env -f deployment/docker/compose.yml run --rm migrate
```

The second run will report all existing migrations as skipped. Never edit an applied
DDL in place; add the next numbered migration instead.

**How it works:**
1. Each DDL file is checksummed (SHA256)
2. Checksums are stored in `agentmesh_schema_migrations` table
3. Only new files or changed files (different checksum) get applied
4. Running multiple times is safe - unchanged DDLs are skipped

## Troubleshooting

- Use `localhost` from Windows and service names such as `postgres` or
  `control-plane`, `supervisor`, or `litellm` only inside the Compose network.
- A healthy container proves process liveness. `/ready` additionally proves registration
  and role readiness.
- `LLM_PROVIDER=groq` requires a valid `GROQ_API_KEY`; use `mock` for credential-free
  local startup.
- A worker role returning `404` from a public Agent Playground `/invoke` request is
  expected; durable worker invocation goes through control-plane dispatch.
- Normal heartbeats update runtime presence without writing audit events. Registration,
  degradation, recovery, stale, draining, and shutdown transitions are audited.
