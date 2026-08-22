# AgentMesh Database

This folder contains deployment-owned PostgreSQL schema assets for local and future
AgentMesh environments. Runtime database operations live in the Python application under
`src/agentmesh`.

## Layout

```text
deployment/
└── postgres/
    ├── ddls/
    └── scripts/
```

## DDLs

DDL files live in:

```text
deployment/postgres/ddls/
```

Files are ordered by prefix and are written to be idempotent:

- missing tables are created
- missing columns are added
- indexes are created if absent
- constraints are added if absent

Current DDLs:

```text
000_agentmesh_schema_migrations.sql
001_agentmesh_events.sql
002_agentmesh_event_claims.sql
003_agentmesh_agents.sql
004_agentmesh_resources.sql
005_agentmesh_resource_audit_events.sql
006_agent_runtime_instances.sql
```

## Core Tables

`agentmesh_agents`
Keeps compatibility with the current registry code and agent-card model.

`agentmesh_resources`
Generic operational inventory for agents, orchestrators, MCP servers, tools, registries, UIs, and services.
Migration `006` adds `agent_runtime` as a resource type, runtime lifecycle states, and
an index for aggregate readiness and stale-instance sweeps. Runtime metadata includes
the stable agent ID, unique process instance ID, role, endpoint, active execution count,
start time, last heartbeat, and last successful model call.

`agentmesh_resource_audit_events`
Audit and progress trail for any row in `agentmesh_resources`.

`agentmesh_events`
Workflow timeline and orchestration event log.

`agentmesh_event_claims`
Worker lease table for safely claiming directed assignments.

`agentmesh_schema_migrations`
Tracks applied DDL files by checksum.

## Apply DDLs

PowerShell:

```powershell
.\deployment\postgres\scripts\apply_ddls.ps1
```

Python:

```powershell
python deployment/postgres/scripts/apply_ddls.py
```

Both commands read `DATABASE_URL` from the environment or root `.env`.

### Automatic Migration via Docker

When using Docker Compose, the `migrate` service is automatically managed:

```powershell
# Start services - migrate rebuilds and applies new/changed DDLs
docker compose --env-file .env -f deployment/docker/compose.yml up -d migrate

# The migrate service:
# - Rebuilds on each start/restart to pick up code changes
# - Applies only new or changed DDLs (idempotent - checksum tracked)
# - Exits with status 0 after completion
# - Orchestrator waits for service_completed_successfully before starting
```

**How it works:**
1. Each DDL file is checksummed (SHA256)
2. Checksums are stored in `agentmesh_schema_migrations` table
3. Only new files or changed files (different checksum) get applied
4. Running multiple times is safe - unchanged DDLs are skipped
5. Never edit an applied DDL in place; add the next numbered migration instead

## Local Postgres

Start Postgres with Docker Compose:

```powershell
docker compose --env-file .env -f deployment/docker/compose.yml up -d postgres
```

Connection:

```text
Host: localhost
Port: 5432
Database: agentmesh
User: agentmesh
Password: agentmesh
```

## Streamlit Dashboard

The Streamlit Resource Dashboard should primarily read:

```text
agentmesh_resources
agentmesh_resource_audit_events
agentmesh_events
```

This keeps the dashboard generic instead of hardcoding only agents. Agents, orchestrators, MCP servers, and tools can all appear as resources and emit audit events.

## Future: Postgres MCP Server

A future `postgres-mcp-server` can expose this database as a controlled tool provider for agents and dashboards.

Recommended scope:

- read resource inventory from `agentmesh_resources`
- read workflow timelines from `agentmesh_events`
- read audit trails from `agentmesh_resource_audit_events`
- append controlled audit notes for existing resources

Keep core lifecycle writes in the application repositories. The MCP server should start as an observability and controlled-tool layer, not as the primary way agents mutate registry, workflow, claim, or run state.
