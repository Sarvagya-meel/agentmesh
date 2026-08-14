---
description: AgentMesh Core product requirements and acceptance criteria
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh Core Requirements

Follow these requirements when implementing or reviewing work in AgentMesh Core.

## Mission

AgentMesh Core provides the Memory Control Plane (MCP): an append-only event log and deterministic state projection store, plus the API, services, orchestrator, and agent infrastructure all workflows depend on.

The system must be fully traceable, replayable, and reconstructable from events alone. Every action is an event. No workflow state exists outside the event log.

## Core requirements

### Event append API

- `POST /events` must persist a valid event atomically and return HTTP 201 with the stored event, assigned `event_id`, and timestamp.
- Reject missing or empty `conversation_id` and `workflow_id` with HTTP 422.
- Reject invalid or unregistered `event_type` values with HTTP 422.
- Reject missing or empty `source_agent` with HTTP 422.
- Reject non-JSON-serializable `payload` with HTTP 422.
- Enforce routing constraints:
  - `DIRECTED` requires `target_agent`
  - `FANOUT` and `CLAIMED` must not include `target_agent`
  - negative `routing_weights` values are invalid
- Use `event_id` as idempotency key and enforce uniqueness for duplicate appends.

### Event query API

- `GET /events` must accept a valid `workflow_id` and return events sorted by timestamp ascending.
- Support filtering by `since`, `event_type`, `source_agent`, `target_agent`, and `limit` with default limit 100.
- When no events exist, return an empty list with HTTP 200.
- Reject requests without `workflow_id` with HTTP 422.

### Workflow start API

- `POST /workflows/start` must append a `WORKFLOW_STARTED` event and return HTTP 201 with `workflow_id` and initial status `RUNNING`.
- Validate `conversation_id`, `workflow_id`, and `goal` as required inputs.
- Enforce `workflow_id` as a valid UUID v4.
- Reject re-starting a workflow that already has a `WORKFLOW_STARTED` event with HTTP 409.

### Current state API

- `GET /state/{workflow_id}` returns the current projected `WorkflowState` for a workflow.
- Include `status`, `current_step`, `assigned_agents`, `last_event_id`, `processed_event_types`, and `pending_event_types`.
- Return HTTP 404 for workflows with no events.
- The response must match replaying the workflow event log through the deterministic projection algorithm.
- Include both `conversation_id` and `workflow_id` in the response.

### Append-only event storage

- The `events` table is immutable: no update or delete operations are allowed on historical rows.
- Repository code must reject attempts to modify existing event rows with a domain exception.
- Query results default to ascending `timestamp` order.
- Each event gets a monotonically increasing `sequence_number` scoped per `workflow_id`.
- `events` must include an index on `(workflow_id, timestamp)` for efficient polling and retrieval.

### Deterministic state projection

- `WorkflowState` must be a pure function of the ordered event list for a workflow.
- Deterministic replay is required for debugging, reproducibility, and disaster recovery.
- State projection must be consistent with the materialized `current_state` cache and with the same event log replayed from scratch.

### Routing and causation rules

- Supported routing modes: `DIRECTED`, `FANOUT`, and `CLAIMED`.
- `causation_chain` must be preserved and validated for loops.
- Event append must reject cycles that would create a self-referential causation chain.
- In `CLAIMED` mode, one agent may claim a specific event at a time via `event_claims` atomic uniqueness.

### Agent and orchestrator behavior

- The Orchestrator makes workflow decisions and emits task events; it does not directly invoke agents.
- Agents execute independently and communicate only through MCP events.
- Source agents must be validated against a registry; `orchestrator` is a valid built-in source.
- Workflows must be traceable and workable from the event log even after a crash or restart.

## Non-functional requirements

- Reliability: event storage and workflow state must be reconstructable from the event log.
- Auditability: all actions must be represented as events with traceable lineage.
- Local-first readiness: development must work via Docker Compose without external services required in v1.
- Reproducibility: deterministic state and versioned models must support debugging and future schema evolution.

## Engineering expectations

- Preserve the API → Service → Storage layering.
- Keep validation and business rules in domain/service code, not route handlers.
- Keep all implementation decisions compatible with append-only, replayable, event-sourced workflows.
- Treat the event log as the system of record.
