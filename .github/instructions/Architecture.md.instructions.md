---
description: AgentMesh architecture, layer boundaries, and implementation guardrails
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh Architecture

Follow these rules when making code changes, answering questions, or reviewing changes in this repository.

## Project context

AgentMesh is a production-grade hybrid multi-agent system for job-search automation and future agentic workflows. The project uses event sourcing, deterministic state projection, and decentralized agent collaboration through the MCP event log.

## Layer overview

The system is organized into five distinct layers. Each layer has a single responsibility and communicates with adjacent layers only through defined interfaces.

```text
┌─────────────────────────────────────────────────────┐
│                     API Layer                        │
│         events.py  │  state.py  │  workflows.py      │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                   Service Layer                      │
│   EventService  │  StateService  │  OrchestratorSvc  │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                   Storage Layer                      │
│       events  │  current_state  │  event_claims      │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                    Agent Layer                       │
│  BaseAgent │ JobDetectorAgent │ EmailFinderAgent      │
│                  ApplicationAgent                    │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                    Core Layer                        │
│      models.py  │  event_types.py  │  exceptions.py  │
└─────────────────────────────────────────────────────┘
```

## Layer responsibilities

### API Layer

Routes: `events`, `state`, `workflows`

- Accept HTTP requests and validate input using Pydantic v2 schemas.
- Delegate all business logic to the service layer.
- Return structured HTTP responses.
- Contain no business logic.

### Service Layer

- `EventService`: append events to MCP, enforce append-only semantics, and validate causation chains.
- `StateService`: project current workflow state from the event log deterministically.
- `OrchestratorService`: evaluate workflow state and emit the next task event(s); make all structured workflow decisions.

### Storage Layer

Three tables form the persistence backbone:

- `events`: append-only event log and source of truth
- `current_state`: materialized projection of current workflow state
- `event_claims`: atomic claim records for `CLAIMED` routing mode

### Agent Layer

- `BaseAgent`: abstract polling loop, claim logic, causation-chain enforcement, and routing dispatch
- `JobDetectorAgent`: polls for `TASK_ASSIGNED` (`task_type=JOB_DETECT`) and emits `JOB_DETECTED` or `TASK_FAILED`
- `EmailFinderAgent`: polls for `TASK_ASSIGNED` (`task_type=EMAIL_FIND`) and emits `EMAIL_FOUND` or `TASK_FAILED`
- `ApplicationAgent`: polls for `TASK_ASSIGNED` (`task_type=APPLY`) and emits `APPLICATION_SENT` or `TASK_FAILED`

Each agent package contains `agent.py`, `schemas.py`, `tools.py`, `prompts.py`, and `config.py`.

### Client Layer

- `MCPClient`: HTTP client used by independently running agents and runners to communicate with MCP without importing the service layer directly.

### Runner Layer

- `run_orchestrator.py`
- `run_job_detector.py`
- `run_email_finder.py`
- `run_applicator.py`

### Core Layer

- `models.py`: Pydantic v2 domain models (`Event`, `WorkflowState`, `Task`, `WorkflowContext`, `EventFilters`)
- `event_types.py`: enum of valid event type strings
- `exceptions.py`: domain exception hierarchy

## Architectural rules

### MCP is append-only

The `events` table is never updated or deleted. Every state change is expressed as a new event appended to the log. This is a hard repository-level constraint.

### State is a deterministic projection

`current_state` is always derived by replaying the event log for a given `workflow_id`. The `StateService` must produce identical output for identical event sequences. There is no mutable state outside the event log.

### Mandatory identifiers

Every event, task, and state record must carry both:

- `conversation_id`: identifies the top-level conversation or session
- `workflow_id`: identifies the specific workflow instance

These fields are required at the API, service, storage, and agent layers. Requests missing either field must be rejected.

### No direct agent-to-agent calls

Agents must never call each other directly (no HTTP calls, no function calls, no shared queues). Collaboration happens exclusively through MCP events. An agent reads events from MCP, does work, and writes result events back to MCP.

### Orchestrator emits, does not invoke

The `OrchestratorService` evaluates workflow state and emits task events such as `TASK_EMAIL_FIND`. It does not call agents directly. Agents discover their tasks by polling MCP for events addressed to them.

### `CLAIMED` events require atomic claim records

When routing mode is `CLAIMED`, only one agent may process a given event. This is enforced by inserting a record into `event_claims(event_id)` with a unique constraint. The first agent to successfully insert wins the claim; all others receive a conflict and skip the event.

### Causation chain must prevent loops

Every event carries a `causation_id` pointing to the event that caused it. Before appending a new event, `EventService` must walk the causation chain to detect cycles. Any event whose causation chain leads back to itself must be rejected with `CausationLoopError`.

## Routing modes

- `DIRECTED`: event is addressed to a specific agent by `agent_id`; only that agent processes it
- `FANOUT`: event is broadcast; all subscribed agents process it independently
- `CLAIMED`: event is available to any eligible agent; the first to atomically claim it wins

## Implementation guidance for code changes

- Preserve the API → Service → Storage layering.
- Keep business logic out of route handlers.
- Treat the event log as the system of record; do not mutate historical events.
- Keep state derivation deterministic and replayable.
- Validate `conversation_id` and `workflow_id` on all relevant inputs.
- Prefer event-driven collaboration over direct agent dependency or shared in-memory state.
- Make any new workflow or event type consistent with the existing event taxonomy and causation model.
- When adding services, keep them stateless and enforce domain invariants in the service layer.

## Future extension points

The following are not implemented in v1, but the architecture must not preclude them:

- Redis Streams / Kafka: the polling-based agent loop can be replaced with a stream consumer without changing agent business logic because agents interact with MCP only through the `EventService` interface.
- Distributed agents: agents can run as separate processes or containers because they are stateless and communicate only through the HTTP API.
- Event schema versioning: `event_types.py` and the Pydantic models should be versioned to support schema evolution.

## Acceptance criteria for work in this repo

When implementing features or fixing issues in AgentMesh, ensure that changes:

1. respect the layer boundaries described above,
2. maintain append-only event sourcing semantics,
3. preserve deterministic state projection behavior,
4. retain required `conversation_id` and `workflow_id` invariants,
5. avoid direct agent-to-agent invocation,
6. and keep the system compatible with future event-driven extension and distribution.
