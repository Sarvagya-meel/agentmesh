---
description: AgentMesh Core implementation design and architecture guidance
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh Core Design

Use this design document as the implementation guidance for the Core system.

## Overview

AgentMesh Core is implemented under `src/agentmesh/` with API, service, storage, agent, and orchestration boundaries. PostgreSQL is the durable source of truth for events, claims, registry cards, resources, audits, and LangGraph checkpoints. The registered supervisor agent makes workflow decisions; worker agents communicate through control-plane APIs and event records.

## Project structure

The expected package structure is:

- `src/agentmesh/main.py`
- `src/agentmesh/api/routes/` for event, state, workflow, registry, and worker APIs
- `src/agentmesh/services/` for event, state-projection, and worker-lease services
- `src/agentmesh/database/postgres/` for PostgreSQL adapters and query logic
- `deployment/postgres/` for ordered PostgreSQL DDL and schema application scripts
- `src/agentmesh/core/models/` package: `workflow.py`, `agent_card.py`, `event_types.py`, `exceptions.py`

## Architectural layers

### API Layer

- Route handlers accept HTTP requests and validate incoming payloads.
- No business logic belongs in the route layer.
- Routes delegate into service methods and return structured responses.

### Service Layer

- `EventService`: validate, persist, and query events; enforce append-only semantics and idempotency.
- `StateService`: derive deterministic projected workflow state from ordered events.
- `WorkerService`: enforce assignment routing and leases, then pass verified results to the supervisor.

### Storage Layer

- Repository protocols isolate event, claim, registry, and resource persistence.
- PostgreSQL adapters live under `src/agentmesh/database/postgres/`.
- DDL and migration SQL live under `deployment/postgres/`.
- Assignment claims use atomic leases so crashed workers can recover safely.

## Database separation

- Raw `CREATE TABLE`, `ALTER TABLE`, and migration SQL live only under `deployment/postgres/`.
- Python adapters under `src/agentmesh/database/postgres/` contain CRUD and query operations only.
- Repository classes do not create tables during initialization.
- Schema creation and migration happens via the deployment migration service or an explicit one-shot DDL apply script.

## Design guardrails

- Keep the event log immutable and append-only.
- Treat workflow state as derived data, never as independent mutable truth.
- Maintain deterministic replay behavior and auditability.
- Keep the codebase compatible with future extension, including alternate backends such as Kafka/Redis streams and distributed agent execution.
