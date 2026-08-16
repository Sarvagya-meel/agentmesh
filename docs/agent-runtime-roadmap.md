# Agent Runtime Roadmap

## Current MVP

1. Run agents as independent long-lived services instead of UI-owned Python objects.
2. Keep agent code runtime-neutral so the same worker can run locally, in Docker, or later in managed infrastructure.
3. Use Docker Compose for local production-like process boundaries.
4. Use PostgreSQL for durable events, claims, resource inventory, and audit history.

## Current Runtime Progress

1. PostgreSQL runs locally through Docker Compose.
2. FastAPI runs as a container and uses PostgreSQL for events, claims, registry cards, and LangGraph checkpoints.
3. `agentmesh-agent-langgraph-copilot` and `agentmesh-agent-googleADK-Chatagent` run as independent workers.
4. Both workers register, heartbeat, poll, lease assignments, and submit results through the control-plane API.
5. `orchestrator-supervisor-agent` is a registered `BaseAgent` implementation with a durable LangGraph workflow.
6. Streamlit provides separate resource, agent playground, and workflow views backed by the API and PostgreSQL timelines.
7. Worker images use a selective Docker build: each image contains shared contracts and `agents/common`, plus only its own concrete agent package.
8. Each concrete agent package owns its factory, FastAPI app, and `python -m` entrypoint, so it runs independently or as part of Compose without changing agent code.

## Next Implementation Order

1. Finish repository cleanup and keep runtime documentation aligned with executable code.
2. Add integration coverage for container startup, registration, assignment leasing, and workflow completion.
3. Add failure recovery tests for expired leases and restarted orchestration.
4. Define the read-only registry MCP adapter contract.
5. Add production deployment adapters without changing agent business logic.

## Future Enhancements By Priority

1. Redis queue for async jobs, retries, locks, and longer-running tasks after the polling model is proven.
2. MCP adapter over the registry for tool-style agent discovery and status checks.
3. Postgres MCP tool server for controlled observability and safe operational reads.
4. RDS PostgreSQL migration by changing `DATABASE_URL`.
5. AgentCore, ECS, Fargate, or Kubernetes hosting for production workloads.
6. Observability with structured logs, traces, metrics, and run-level audit records.

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
