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
│    EventService  │  StateService  │  WorkerService    │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                   Storage Layer                      │
│       events  │  current_state  │  event_claims      │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                    Agent Layer                       │
│ BaseAgent │ SupervisorAgent │ LangGraph │ Google ADK  │
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
- **WorkerService**: Enforces assignment routing and leases, then submits verified results to the supervisor agent

### Storage Layer

Three tables form the persistence backbone:

| Table | Purpose |
|-------|---------|
| `events` | Append-only event log — the single source of truth |
| `current_state` | Materialized projection of current workflow state (cache) |
| `event_claims` | Atomic claim records for CLAIMED routing mode |

### Agent Layer

- **BaseAgent** (`agents/common/agent_models/base_agent.py`): Shared identity, AgentCard, registration, and `run_task` contract
- **MasterOrchestratorAgent** (`agents/agent_langgraph_orchestrator_supervisor/`): Registered supervisor for plans, approvals, assignments, and completion
- **ConversationAgent** (`agents/agent_langgraph_copilot/`): LangGraph chat and review worker
- **GoogleADKAgent** (`agents/agent_adk_spark/`): Google ADK chat, planning, and research worker

Agent packages contain only modules with implemented behavior. Add schemas, tools, prompts, or configuration when they carry real code.

### Client Layer

- **ControlPlaneClient** (`clients/control_plane_client.py`): REST client used by independent workers for registry and assignment APIs.

### Runner Layer

- **run_langgraph_agent.py**: Independent LangGraph worker entrypoint
- **run_google_adk_agent.py**: Independent Google ADK worker entrypoint

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

### Supervisor Emits, Does Not Invoke
The supervisor agent evaluates workflow state and emits directed `TASK_ASSIGNED` events. It does not call workers directly. Workers discover assignments through the control-plane API.

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

- **Redis Streams / Kafka**: The polling loop can be replaced with a stream consumer without changing agent business logic because workers use stable control-plane contracts.
- **Distributed agents**: Agents can run as separate processes or containers because they are stateless and communicate only through the HTTP API.
- **Event schema versioning**: The `event_types.py` enum and Pydantic models should be versioned to support schema evolution.
