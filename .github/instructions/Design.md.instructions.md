---
description: AgentMesh Core implementation design and architecture guidance
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh Core Design

Use this design document as the authoritative implementation guidance for the Core system.

## Overview

AgentMesh Core is implemented under `src/agentmesh/` with a strict API → Service → Storage architecture. The Memory Control Plane (MCP) is the single source of truth: an append-only event log plus deterministic state projection. The Orchestrator makes workflow decisions; agents act independently and communicate only through event records.

## Project structure

The expected package structure is:

- `src/agentmesh/main.py`
- `src/agentmesh/api/routes/events.py`, `state.py`, `workflows.py`
- `src/agentmesh/services/event_service.py`, `state_service.py`, `orchestrator_service.py`
- `src/agentmesh/storage/models.py`, `repository.py`, `migrations/`
- `src/agentmesh/agents/base.py` and package-based agents for job detection, email finding, and application tasks
- `src/agentmesh/clients/mcp_client.py`
- `src/agentmesh/runners/` for independently executable entrypoints
- `src/agentmesh/core/models.py`, `event_types.py`, `exceptions.py`

## Architectural layers

### API Layer

- Route handlers accept HTTP requests and validate incoming payloads.
- No business logic belongs in the route layer.
- Routes delegate into service methods and return structured responses.

### Service Layer

- `EventService`: validate, persist, and query events; enforce append-only semantics and idempotency.
- `StateService`: derive deterministic projected workflow state from ordered events and maintain the materialized `current_state` cache.
- `OrchestratorService`: read workflow state, decide what action is next, and emit task events without calling agents directly.

### Storage Layer

- `EventRepository`, `StateRepository`, and `ClaimRepository` define contract interfaces.
- PostgreSQL implementations use SQLAlchemy async + asyncpg.
- Event claims support `CLAIMED` routing via atomic uniqueness checks.

### Agent Layer

- `BaseAgent` implements the shared polling loop and dispatch logic.
- Agent packages are independent and stateless between cycles.
- All collaboration must occur via MCP events.

### Core Layer

- `models.py` contains domain dataclasses and enums.
- `event_types.py` registers valid event types.
- `exceptions.py` defines the domain exception hierarchy.

## Required domain models

- `RoutingMode` — `DIRECTED`, `FANOUT`, `CLAIMED`
- `WorkflowStatus` — `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`
- `Event`
- `WorkflowState`
- `Task`
- `WorkflowContext`
- `EventFilters`
- `WorkflowDecision`

Important invariants:
- Every event includes `conversation_id` and `workflow_id`.
- `workflow_id` is a UUID v4.
- `source_agent` must be in a known registry or be `orchestrator`.
- `routing_mode` and `target_agent` are mutually constrained.
- `causation_chain` stores ancestor event IDs in root-to-parent order.

## Event model and validation rules

- `event_type` must be in the registered event types set.
- `payload` must be JSON-serializable.
- `routing_weights` must be non-negative when present.
- `causation_chain` values must be valid UUIDs.
- `DIRECTED` requires a `target_agent`.
- `FANOUT` and `CLAIMED` must not provide `target_agent`.

## MCP interface contract

The system should expose an interface equivalent to:

```python
class MCPInterface(Protocol):
    async def append_event(self, event: Event) -> Event: ...
    async def get_events(self, filters: EventFilters) -> list[Event]: ...
    async def get_state(self, workflow_id: str) -> WorkflowState: ...
    async def try_claim_event(self, event_id: UUID, agent_id: str) -> bool: ...
```

## Agent responsibilities

- `JobDetectorAgent`: polls for `TASK_ASSIGNED` with `task_type=JOB_DETECT` and emits `JOB_DETECTED` or `TASK_FAILED`.
- `EmailFinderAgent`: polls for `TASK_ASSIGNED` with `task_type=EMAIL_FIND` and emits `EMAIL_FOUND` or `TASK_FAILED`.
- `ApplicationAgent`: polls for `TASK_ASSIGNED` with `task_type=APPLY` and emits `APPLICATION_SENT` or `TASK_FAILED`.

Each package includes `agent.py`, `schemas.py`, `tools.py`, `prompts.py`, and `config.py`.

## Runners and clients

- `MCPClient` provides HTTP access to MCP for standalone agents and runners.
- Runner entrypoints are separate processes for orchestrator and agent workloads.
- Runners must not import service-layer logic directly when they can use the client HTTP boundary.

## Design guardrails

- Keep the event log immutable and append-only.
- Treat workflow state as derived data, never as independent mutable truth.
- Maintain deterministic replay behavior and auditability.
- Keep the codebase compatible with future extension, including alternate backends such as Kafka/Redis streams and distributed agent execution.
- Prefer interfaces and injected dependencies over hardcoded internals.

## Implementation expectations

- Build the project as a sequence of phases, preserving the ordering and quality gates in the task plan.
- Validate inputs at the domain/service layer and keep route handlers thin.
- Match the architectural layering and naming conventions exactly when implementing new code.
