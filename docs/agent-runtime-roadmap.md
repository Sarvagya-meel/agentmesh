# Agent Runtime Roadmap

## Current MVP

1. Run agents as independent long-lived services instead of UI-owned Python objects.
2. Keep agent code runtime-neutral so the same worker can run locally, in Docker, or later in managed infrastructure.
3. Use Docker Compose for local production-like process boundaries.
4. Use PostgreSQL for durable events, claims, resource inventory, and audit history.

## Current Runtime Progress

1. PostgreSQL runs locally through Docker Compose.
2. FastAPI API runs as a container and uses PostgreSQL for the event store.
3. `langgraph-agent` runs as an independent container.
4. `langgraph-agent` heartbeats into `agentmesh_resources`.
5. `langgraph-agent` emits resource audit events for heartbeat, assignment claim, and assignment completion.

## Next Implementation Order

1. Add `adk-agent` as an independent Docker Compose service.
2. Verify `adk-agent` appears in `agentmesh_resources`.
3. Verify `adk-agent` claim/completion events appear in `agentmesh_resource_audit_events`.
4. Move registry persistence from in-memory compatibility mode to PostgreSQL.
5. Move orchestrator runtime state and checkpointing to durable PostgreSQL mode.
6. Add Streamlit views that primarily read `agentmesh_resources`, `agentmesh_resource_audit_events`, and `agentmesh_events`.

## Future Enhancements By Priority

1. Registry service backed by PostgreSQL for agent cards, capabilities, status, and heartbeat.
2. Orchestrator service fully wired to durable PostgreSQL tasks, runs, approvals, and workflow timelines.
3. Streamlit operator UI that talks to the orchestrator for commands and reads Postgres-backed resource tables for progress.
4. Redis queue for async jobs, retries, locks, and longer-running tasks after the polling model is proven.
5. MCP adapter over the registry for tool-style agent discovery and status checks.
6. Postgres MCP tool server for controlled observability and safe operational reads.
7. Real LangGraph model provider configuration per environment.
8. Real Google ADK model provider configuration per environment.
9. RDS PostgreSQL migration by changing `DATABASE_URL`.
10. AgentCore, ECS, Fargate, or Kubernetes hosting for production workloads.
11. Observability with structured logs, traces, metrics, and run-level audit records.

## Future: Postgres MCP Tool Server

A future `postgres-mcp-server` should expose curated database tools to agents and operators without replacing the core application repositories.

Initial tools:

- `query_resource_status`
- `get_workflow_timeline`
- `get_resource_audit_trail`
- `lookup_agent_capabilities`
- `append_audit_note`

Rules:

- Core lifecycle writes stay in AgentMesh application services and repositories.
- MCP tools start as observability and controlled-read tools.
- Raw SQL is disabled by default.
- If raw SQL is enabled later, it must be read-only, schema-scoped, and separately configured from production credentials.
- The MCP server registers itself in `agentmesh_resources` as `resource_type='mcp_server'`.
- Tool calls emit audit rows into `agentmesh_resource_audit_events`.

## Runtime Rules

- Agent code reads configuration from environment variables.
- The orchestrator should not know whether an agent runs locally, in Docker, AgentCore, ECS, Fargate, or Kubernetes.
- Agents communicate with the control plane through stable API contracts, not direct imports.
- Agents expose durable lifecycle state through registry/resource records and audit events.
- MCP is an adapter/tooling layer later, not the primary registry API for the MVP.
