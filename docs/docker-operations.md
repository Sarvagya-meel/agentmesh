# Docker Operations

Run commands from the repository root. Copy `.env.example` to `.env`, keep credentials
only in the ignored `.env`, and choose exactly one Compose profile through
`COMPOSE_PROFILES`. Do not add a second profile with the `--profile` flag.

> Internal control-plane routes use `INTERNAL_SERVICE_TOKEN`. Public agent and UI ports
> remain local-development surfaces and should not be exposed directly to the internet.

## Quick Start

The easiest way to manage the stack is using the PowerShell helper scripts in `scripts/`:

```powershell
# Start existing images. This does not rebuild images or recreate unchanged containers.
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service all

# Recreate containers and rebuild changed images. This reloads .env and source changes.
pwsh -File scripts\docker_component_manager.ps1 -Action restart -Service all

# Destroy all AgentMesh resources and rebuild the entire stack from scratch.
pwsh -File scripts\docker_component_manager.ps1 -Action rebuild -Service all

# Check health of all endpoints
pwsh -File scripts\docker_component_manager.ps1 -Action health

# View logs for all services
pwsh -File scripts\docker_component_manager.ps1 -Action logs -Service all

# Stop all services
pwsh -File scripts\docker_component_manager.ps1 -Action stop -Service all

# Restart one changed service and reload its environment.
pwsh -File scripts\docker_component_manager.ps1 -Action restart -Service streamlit
```

The scripts automatically:
- Detect your `COMPOSE_PROFILES` setting from `.env`
- Apply the correct service set (combined or split profile)
- Wait for services to be healthy before returning

### Lifecycle Actions

| Action | Behavior | Data impact |
| --- | --- | --- |
| `start` | Runs `docker compose up -d` and uses the current local images. Use it when no code, DDL, or environment value changed. | Preserves the PostgreSQL volume. |
| `restart` | Runs `docker compose up -d --build --force-recreate`. Compose rereads `.env`, rebuilds images containing changed source or DDL files, and recreates the selected containers. | Preserves the PostgreSQL volume and existing workflow data. |
| `rebuild` | Runs Compose `down` with volumes and images, prunes the Docker builder cache, builds every image with `--no-cache --pull`, and respawns the full stack. | **Deletes the AgentMesh PostgreSQL volume and all stored workflow data.** |

`rebuild` is always a full-stack operation and requires `-Service all`. Use `restart`
for a code or `.env` change when durable database state must be retained.

For the older combined local sequence, use the sequential helper:

```powershell
# Start in order: registry/control plane -> streamlit -> agent(s)
pwsh -File scripts\start_registry_streamlit_agent.ps1
```

## Docker Compose (Base Commands)

For advanced use, these are the equivalent Docker Compose lifecycle commands:

```powershell
# Start: reuse current images.
docker compose --env-file .env -f deployment/docker/compose.yml up -d

# Restart: reread .env, rebuild changed files, and recreate containers.
docker compose --env-file .env -f deployment/docker/compose.yml up -d --build --force-recreate

# Rebuild: destructive scratch build, including a fresh database volume.
docker compose --env-file .env -f deployment/docker/compose.yml down --volumes --rmi all --remove-orphans
docker builder prune --all --force
docker compose --env-file .env -f deployment/docker/compose.yml build --no-cache --pull
docker compose --env-file .env -f deployment/docker/compose.yml up -d

docker compose --env-file .env -f deployment/docker/compose.yml ps
docker compose --env-file .env -f deployment/docker/compose.yml logs --tail 100
docker compose --env-file .env -f deployment/docker/compose.yml config
```

**Note:** The `migrate` service runs once and exits. When its image contains a new DDL:
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

The Google ADK service requires `LLM_PROVIDER=groq`, a nonempty `GROQ_API_KEY`,
and an ADK-compatible `GOOGLE_ADK_MODEL` for live responses. Missing or invalid live
configuration fails explicitly; the service does not return a synthetic fallback
answer.

The Streamlit container intentionally has no `DATABASE_URL`. Its Registry, Agent
Playground, live workflow event flow, checkpoint recovery, and LangSmith controls
use the control-plane HTTP API. `Open LangSmith trace` appears only when tracing is
enabled and the correlated workflow trace is available.

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

For two fresh build/test rounds, including opt-in live Streamlit behavior and
desktop/mobile browser checks, see [Demo Validation](demo-validation.md).

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
  -Action restart -Service agent-langgraph-copilot
pwsh -File .\scripts\docker_component_manager.ps1 `
  -Action logs -Service control-plane,supervisor
```

## Migrations

The `migrate` service runs once per container lifecycle. Use `restart` after adding a
DDL so its image is rebuilt; it then applies only new migrations (checksum-tracked and
idempotent). `start` intentionally uses the current migration image.

```powershell
# Rebuild and recreate migrate so a newly added DDL is included.
docker compose --env-file .env -f deployment/docker/compose.yml up -d --build --force-recreate migrate

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
