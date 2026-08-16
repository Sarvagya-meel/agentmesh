# AgentMesh Database

This folder contains database-owned assets for local and future production AgentMesh deployments.

## Layout

```text
db/
└── postgress/
    ├── ddls/
    └── script/
```

`postgress` intentionally matches the current project folder name. It contains PostgreSQL DDLs and scripts.

## DDLs

DDL files live in:

```text
db/postgress/ddls/
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
```

## Core Tables

`agentmesh_agents`
Keeps compatibility with the current registry code and agent-card model.

`agentmesh_resources`
Generic operational inventory for agents, orchestrators, MCP servers, tools, registries, UIs, and services.

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
.\db\postgress\script\apply_ddls.ps1
```

Python:

```powershell
python db/postgress/script/apply_ddls.py
```

Both commands read `DATABASE_URL` from the environment or root `.env`.

## Local Postgres

Start Postgres with Docker Compose:

```powershell
docker compose up -d postgres
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
