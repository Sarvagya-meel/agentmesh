# AgentMesh PostgreSQL DDLs

This folder owns the local PostgreSQL schema files for AgentMesh.

## Layout

```text
db/postgress/ddls/
db/postgress/script/
```

The `ddls` folder contains ordered, idempotent SQL files. Each file owns one schema concern.

Current schema concerns:

- `agentmesh_schema_migrations`: tracks which DDL files were applied and whether their checksums changed.
- `agentmesh_events`: append-only workflow/event stream used by orchestrator and workers.
- `agentmesh_event_claims`: leases for workers claiming directed task assignments.
- `agentmesh_agents`: agent-card metadata for known worker agents.
- `agentmesh_resources`: generic inventory for agents, orchestrators, MCP servers, tools, registries, UIs, and services.
- `agentmesh_resource_audit_events`: audit/progress stream attached to any resource.

The `script` folder contains runners that iterate through all DDL files in order. The runner records checksums in `agentmesh_schema_migrations`; unchanged files are skipped, and changed files are re-run so idempotent table/index updates are applied.

## Apply

```powershell
.\db\postgress\script\apply_ddls.ps1
```

Or:

```powershell
python db/postgress/script/apply_ddls.py
```

Both commands read `DATABASE_URL` from the environment or root `.env`.
