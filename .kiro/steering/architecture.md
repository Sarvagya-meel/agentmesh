# AgentMesh — Architecture

## Layer Overview

The system is organized into five distinct layers. Each layer has a single responsibility and communicates with adjacent layers only through defined interfaces.

```
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

## Layer Responsibilities

### API Layer
Routes: `events`, `state`, `workflows`

- Accepts HTTP requests and validates input using Pydantic v2 schemas
- Delegates all business logic to the Service layer
- Returns structured HTTP responses
- Contains no business logic

### Service Layer

- **EventService**: Appends events to MCP, enforces append-only semantics, validates causation chains
- **StateService**: Projects current workflow state from the event log deterministically
- **OrchestratorService**: Evaluates workflow state and emits the next task event(s); makes all structured workflow decisions

### Storage Layer

Three tables form the persistence backbone:

| Table | Purpose |
|-------|---------|
| `events` | Append-only event log — the single source of truth |
| `current_state` | Materialized projection of current workflow state (cache) |
| `event_claims` | Atomic claim records for CLAIMED routing mode |

### Agent Layer

- **BaseAgent** (`agents/base.py`): Abstract polling loop, claim logic, causation chain enforcement, routing dispatch
- **JobDetectorAgent** (`agents/job_detector/`): Package. Polls for `TASK_ASSIGNED` (task_type=JOB_DETECT), emits `JOB_DETECTED` or `TASK_FAILED`
- **EmailFinderAgent** (`agents/email_finder/`): Package. Polls for `TASK_ASSIGNED` (task_type=EMAIL_FIND), emits `EMAIL_FOUND` or `TASK_FAILED`
- **ApplicationAgent** (`agents/applicator/`): Package. Polls for `TASK_ASSIGNED` (task_type=APPLY), emits `APPLICATION_SENT` or `TASK_FAILED`

Each agent package contains: `agent.py` (main class), `schemas.py` (I/O models), `tools.py` (external integrations), `prompts.py` (LLM prompts), `config.py` (agent settings).

### Client Layer

- **MCPClient** (`clients/mcp_client.py`): HTTP client wrapping the MCP API. Used by independently running agents and runners to communicate with MCP without importing the service layer directly.

### Runner Layer

- **run_orchestrator.py**: Independent entrypoint for the Orchestrator process
- **run_job_detector.py**: Independent entrypoint for JobDetectorAgent
- **run_email_finder.py**: Independent entrypoint for EmailFinderAgent
- **run_applicator.py**: Independent entrypoint for ApplicationAgent

### Core Layer

- **models.py**: Pydantic v2 domain models (`Event`, `WorkflowState`, `Task`, `WorkflowContext`, `EventFilters`)
- **event_types.py**: Enum of all valid event type strings
- **exceptions.py**: Domain exception hierarchy

---

## Architectural Rules

### MCP is Append-Only
The `events` table is never updated or deleted. Every state change is expressed as a new event appended to the log. This is a hard constraint enforced at the repository layer.

### State is a Deterministic Projection
`current_state` is always derived by replaying the event log for a given `workflow_id`. The `StateService` must produce identical output for identical event sequences. There is no mutable state outside the event log.

### Mandatory Identifiers
Every event, task, and state record **must** carry both:
- `conversation_id` — identifies the top-level conversation/session
- `workflow_id` — identifies the specific workflow instance

These fields are required at the API, service, storage, and agent layers. Requests missing either field must be rejected.

### No Direct Agent-to-Agent Calls
Agents must never call each other directly (no HTTP calls, no function calls, no shared queues between agents). All agent collaboration happens exclusively through MCP events. An agent reads events from MCP, does work, and writes result events back to MCP.

### Orchestrator Emits, Does Not Invoke
The OrchestratorService evaluates workflow state and emits task events (e.g., `TASK_EMAIL_FIND`). It does not call agents directly. Agents discover their tasks by polling MCP for events addressed to them.

### CLAIMED Events Require Atomic Claim Records
When routing mode is `CLAIMED`, only one agent may process a given event. This is enforced by inserting a record into `event_claims(event_id)` with a unique constraint. The first agent to successfully insert wins the claim; all others receive a conflict error and skip the event.

### Causation Chain Must Prevent Loops
Every event carries a `causation_id` pointing to the event that caused it. Before appending a new event, the EventService must walk the causation chain to detect cycles. An event whose causation chain leads back to itself must be rejected with a `CausationLoopError`.

---

## Routing Modes

| Mode | Behavior |
|------|---------|
| `DIRECTED` | Event is addressed to a specific agent by `agent_id`; only that agent processes it |
| `FANOUT` | Event is broadcast; all subscribed agents process it independently |
| `CLAIMED` | Event is available to any eligible agent; first to atomically claim it wins |

---

## Future Extension Points

The following are **not implemented in v1** but the architecture must not preclude them:

- **Redis Streams / Kafka**: The polling-based agent loop can be replaced with a stream consumer without changing agent business logic, because agents interact with MCP only through the `EventService` interface.
- **Distributed agents**: Agents can run as separate processes or containers because they are stateless and communicate only through the HTTP API.
- **Event schema versioning**: The `event_types.py` enum and Pydantic models should be versioned to support schema evolution.
