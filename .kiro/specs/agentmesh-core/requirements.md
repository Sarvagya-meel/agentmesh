# Requirements Document

## Introduction

AgentMesh Core is the foundational layer of a production-grade hybrid multi-agent system. It provides the Memory Control Plane (MCP) — an append-only event log and state projection store — together with the API, service, orchestrator, and agent infrastructure that all workflows depend on.

The system must be fully traceable, replayable, and reconstructable from events alone. Every action is an event. No state exists outside the event log.

---

## Glossary

| Term | Definition |
|------|-----------|
| MCP | Memory Control Plane — the append-only event store and state projection service |
| Event | An immutable record of something that happened, carrying `conversation_id`, `workflow_id`, `event_type`, `source_agent`, and `payload` |
| Workflow | A named sequence of agent tasks coordinated by the Orchestrator |
| `conversation_id` | Identifies the top-level session or conversation that spawned a workflow |
| `workflow_id` | Identifies a specific workflow instance; must be non-guessable (UUID v4) |
| `event_id` | Globally unique identifier for a single event; used as idempotency key |
| Routing Mode | One of `DIRECTED`, `FANOUT`, or `CLAIMED` — controls which agents process an event |
| Causation Chain | Ordered list of ancestor event IDs from workflow root to immediate parent |
| State Projection | Deterministic function that derives `WorkflowState` from an ordered event list |
| Claim | An atomic record in `event_claims` that grants one agent exclusive processing rights |
| Source Agent | The agent or orchestrator that emitted an event; validated against a known registry |

---

## Requirements

---

### Requirement 1: Event Append API

**User Story:** As an agent or orchestrator, I want to append an event to MCP so that every action is durably recorded and visible to all other components.

#### Acceptance Criteria

1. WHEN a `POST /events` request is received with a valid event body, THEN the system SHALL persist the event atomically and return HTTP 201 with the stored event including its assigned `event_id` and `timestamp`.
2. WHEN a `POST /events` request is received, THEN the system SHALL reject any request where `conversation_id` is absent or empty with HTTP 422.
3. WHEN a `POST /events` request is received, THEN the system SHALL reject any request where `workflow_id` is absent or empty with HTTP 422.
4. WHEN a `POST /events` request is received, THEN the system SHALL reject any request where `event_type` is not a registered event type with HTTP 422.
5. WHEN a `POST /events` request is received, THEN the system SHALL reject any request where `source_agent` is absent or empty with HTTP 422.
6. WHEN a `POST /events` request is received, THEN the system SHALL reject any request where `payload` is not a JSON-serializable object with HTTP 422.
7. WHEN a `POST /events` request is received with a `routing_mode` of `DIRECTED` and no `target_agent`, THEN the system SHALL reject the request with HTTP 422.
8. WHEN a `POST /events` request is received with a `routing_mode` of `CLAIMED` or `FANOUT` and a `target_agent` is set, THEN the system SHALL reject the request with HTTP 422.
9. WHEN a `POST /events` request is received with `routing_weights` set, THEN the system SHALL reject the request if any weight value is negative with HTTP 422.

---

### Requirement 2: Event Query API

**User Story:** As an agent or orchestrator, I want to query events from MCP so that I can discover what has happened in a workflow and decide what to do next.

#### Acceptance Criteria

1. WHEN a `GET /events` request is received with a valid `workflow_id` query parameter, THEN the system SHALL return HTTP 200 with an ordered list of events for that workflow, sorted by `timestamp` ascending.
2. WHEN a `GET /events` request is received with a `since` query parameter, THEN the system SHALL return only events with `timestamp` strictly after the given value.
3. WHEN a `GET /events` request is received with an `event_type` query parameter, THEN the system SHALL return only events matching that type.
4. WHEN a `GET /events` request is received with a `source_agent` query parameter, THEN the system SHALL return only events emitted by that agent.
5. WHEN a `GET /events` request is received with a `target_agent` query parameter, THEN the system SHALL return only events directed at that agent.
6. WHEN a `GET /events` request is received with a `limit` parameter, THEN the system SHALL return at most that many events; the default limit SHALL be 100.
7. WHEN a `GET /events` request is received without a `workflow_id`, THEN the system SHALL reject the request with HTTP 422.
8. WHEN a `GET /events` request is received for a `workflow_id` with no events, THEN the system SHALL return HTTP 200 with an empty list.

---

### Requirement 3: Workflow Start API

**User Story:** As a client, I want to start a new workflow so that the Orchestrator can begin coordinating agents toward a goal.

#### Acceptance Criteria

1. WHEN a `POST /workflows/start` request is received with a valid `conversation_id`, `workflow_id`, and `goal`, THEN the system SHALL append a `WORKFLOW_STARTED` event and return HTTP 201 with the `workflow_id` and initial status `RUNNING`.
2. WHEN a `POST /workflows/start` request is received, THEN the system SHALL reject any request where `conversation_id` is absent or empty with HTTP 422.
3. WHEN a `POST /workflows/start` request is received, THEN the system SHALL reject any request where `workflow_id` is absent or empty with HTTP 422.
4. WHEN a `POST /workflows/start` request is received, THEN the system SHALL reject any request where `workflow_id` is not a valid UUID v4 with HTTP 422.
5. WHEN a `POST /workflows/start` request is received with a `workflow_id` that already has a `WORKFLOW_STARTED` event, THEN the system SHALL return HTTP 409 Conflict.
6. WHEN a `POST /workflows/start` request is received, THEN the system SHALL reject any request where `goal` is absent or empty with HTTP 422.

---

### Requirement 4: Current State API

**User Story:** As an agent or orchestrator, I want to retrieve the current projected state of a workflow so that I can make decisions based on what has already happened.

#### Acceptance Criteria

1. WHEN a `GET /state/{workflow_id}` request is received for an existing workflow, THEN the system SHALL return HTTP 200 with the current `WorkflowState` including `status`, `current_step`, `assigned_agents`, `last_event_id`, `processed_event_types`, and `pending_event_types`.
2. WHEN a `GET /state/{workflow_id}` request is received for a workflow with no events, THEN the system SHALL return HTTP 404.
3. WHEN a `GET /state/{workflow_id}` request is received, THEN the returned state SHALL be consistent with the result of replaying all events for that `workflow_id` through the projection algorithm.
4. WHEN a `GET /state/{workflow_id}` request is received, THEN the response SHALL include both `conversation_id` and `workflow_id`.

---

### Requirement 5: Append-Only Event Storage

**User Story:** As a system operator, I want the event store to be strictly append-only so that the audit trail is immutable and workflows can always be replayed.

#### Acceptance Criteria

1. WHEN an event is persisted to the `events` table, THEN the system SHALL never update or delete that row under any circumstances.
2. WHEN the repository layer receives a request to modify an existing event, THEN the system SHALL raise a domain exception and reject the operation.
3. WHEN the `events` table is queried, THEN the system SHALL return events in ascending `timestamp` order by default.
4. WHEN an event is appended, THEN the system SHALL assign a monotonically increasing `sequence_number` scoped to the `workflow_id`.
5. WHEN the `events` table is created, THEN it SHALL have an index on `(workflow_id, timestamp)` to support efficient polling queries.

---

### Requirement 6: Deterministic State Projection

**User Story:** As a developer, I want state to be a pure deterministic function of the event log so that I can always reconstruct any workflow's state by replaying its events.

#### Acceptance Criteria

1. WHEN `project_state` is called with the same ordered list of events, THEN the system SHALL always return an identical `WorkflowState` regardless of when or how many times it is called.
2. WHEN `project_state` is called with an empty event list, THEN the system SHALL return a `WorkflowState` with `status=PENDING` and all list fields empty.
3. WHEN a `WORKFLOW_STARTED` event is processed by `project_state`, THEN the returned state SHALL have `status=RUNNING`.
4. WHEN a `TASK_ASSIGNED` event is processed by `project_state`, THEN the `target_agent` SHALL be added to `assigned_agents` and `current_step` SHALL be updated.
5. WHEN a `TASK_COMPLETED` event is processed by `project_state`, THEN the originating event type SHALL be added to `processed_event_types`.
6. WHEN a `WORKFLOW_COMPLETED` event is processed by `project_state`, THEN the returned state SHALL have `status=COMPLETED`.
7. WHEN a `WORKFLOW_FAILED` event is processed by `project_state`, THEN the returned state SHALL have `status=FAILED`.
8. WHEN `project_state` is called, THEN the function SHALL perform no I/O — it is a pure function operating only on its input.
9. WHEN `get_current_state(workflow_id)` is called, THEN the returned state SHALL equal `project_state(get_events(workflow_id))`.

---

### Requirement 7: Directed Routing

**User Story:** As an orchestrator, I want to direct an event to a specific agent so that only that agent processes the assigned task.

#### Acceptance Criteria

1. WHEN an event with `routing_mode=DIRECTED` and a `target_agent` is appended, THEN only the agent whose `agent_id` matches `target_agent` SHALL process that event.
2. WHEN an agent polls for events and receives a `DIRECTED` event addressed to a different agent, THEN the agent SHALL skip that event without processing it.
3. WHEN an agent polls for events and receives a `DIRECTED` event addressed to itself, THEN the agent SHALL process the event exactly once.

---

### Requirement 8: Fanout Routing

**User Story:** As an agent, I want to broadcast an event to all subscribed agents so that multiple agents can react to the same occurrence independently.

#### Acceptance Criteria

1. WHEN an event with `routing_mode=FANOUT` and no `target_agent` is appended, THEN all agents subscribed to that `event_type` SHALL independently process the event.
2. WHEN an event with `routing_mode=FANOUT` and `routing_weights` is appended, THEN only the agent with the highest weight value SHALL process the event.
3. WHEN two agents have equal highest weight in a `FANOUT` event, THEN both agents SHALL process the event.
4. WHEN an agent is not subscribed to the `event_type` of a `FANOUT` event, THEN that agent SHALL not process the event.

---

### Requirement 9: Claimed Routing with Atomic Event Claim

**User Story:** As an agent, I want to exclusively claim a CLAIMED event so that exactly one agent processes it even when multiple agents are eligible.

#### Acceptance Criteria

1. WHEN an event with `routing_mode=CLAIMED` is appended, THEN the first agent to atomically insert a record into `event_claims(event_id, agent_id)` SHALL be granted the claim.
2. WHEN an agent successfully claims an event, THEN the system SHALL return a success indicator and the agent SHALL proceed to process the event.
3. WHEN an agent attempts to claim an event that is already claimed, THEN the system SHALL return a failure indicator and the agent SHALL skip the event without processing it.
4. WHEN two agents attempt to claim the same event concurrently, THEN exactly one SHALL succeed and the other SHALL fail — guaranteed by a unique constraint on `event_claims(event_id)`.
5. WHEN a claim attempt fails due to a database conflict, THEN the system SHALL NOT raise an unhandled exception — it SHALL return `False` to the caller.
6. WHEN an agent holds a claim on an event, THEN no other agent SHALL be able to claim the same event.
7. WHEN the `event_claims` table is queried for a given `event_id`, THEN it SHALL return at most one record.

---

### Requirement 10: Causation Chain and Loop Prevention

**User Story:** As a system operator, I want every event to carry its full causation ancestry so that the system can detect and prevent infinite agent loops.

#### Acceptance Criteria

1. WHEN an agent emits a child event in response to a parent event, THEN the child event's `causation_chain` SHALL contain all entries from the parent's `causation_chain` plus the parent's `event_id` appended at the end.
2. WHEN a root event (e.g., `WORKFLOW_STARTED`) is appended, THEN its `causation_chain` SHALL be an empty list.
3. WHEN an agent's `agent_id` appears anywhere in an incoming event's `causation_chain`, THEN the agent SHALL NOT process that event.
4. WHEN loop detection triggers, THEN the agent SHALL emit a `TASK_FAILED` event with `reason: "recursion_loop_detected"` and the offending `event_id` in the payload.
5. WHEN `EventService.append_event` receives an event whose `causation_chain` contains the event's own `event_id`, THEN the system SHALL reject it with a `CausationLoopError`.
6. WHEN `causation_chain` entries are validated, THEN each entry SHALL be a valid UUID; invalid entries SHALL cause the append to be rejected with HTTP 422.

---

### Requirement 11: Agent Polling Loop

**User Story:** As an agent, I want to continuously poll MCP for new events so that I can react to tasks assigned to me without requiring direct calls from other components.

#### Acceptance Criteria

1. WHEN an agent's polling loop starts, THEN it SHALL continuously call `GET /events` with `since=last_seen` to retrieve only new events.
2. WHEN an agent receives an event, THEN it SHALL apply all four guards in order: (1) subscription filter, (2) processed event type check, (3) pending event type check, (4) causation loop check.
3. WHEN an agent processes an event, THEN it SHALL update `last_seen` to the event's `timestamp` before moving to the next event.
4. WHEN an agent's polling loop encounters an MCP error, THEN it SHALL log the error and retry with exponential backoff rather than crashing.
5. WHEN an agent finishes processing an event, THEN it SHALL emit a result event (`TASK_COMPLETED` or `TASK_FAILED`) back to MCP before polling for the next event.
6. WHEN an agent is restarted, THEN it SHALL be able to resume from the last processed event by replaying events from MCP — no local state is required.

---

### Requirement 12: Orchestrator Decision Loop

**User Story:** As a workflow coordinator, I want the Orchestrator to continuously evaluate workflow state and emit the next task event so that workflows progress without manual intervention.

#### Acceptance Criteria

1. WHEN the Orchestrator's decision loop runs, THEN it SHALL read fresh state from MCP on every iteration — no local state caching between iterations.
2. WHEN the Orchestrator decides to assign a task, THEN it SHALL emit a `TASK_ASSIGNED` event with `routing_mode=DIRECTED` and the target agent's ID — it SHALL NOT call the agent directly.
3. WHEN the Orchestrator decides a workflow is complete, THEN it SHALL emit a `WORKFLOW_COMPLETED` event and stop the loop.
4. WHEN the Orchestrator decides a workflow has failed, THEN it SHALL emit a `WORKFLOW_FAILED` event and stop the loop.
5. WHEN the Orchestrator's decision function is called with the same `WorkflowState`, THEN it SHALL always return the same `WorkflowDecision` — the function is deterministic and pure.
6. WHEN the Orchestrator emits any event, THEN that event SHALL carry both `conversation_id` and `workflow_id`.
7. WHEN the Orchestrator encounters an MCP error, THEN it SHALL log the error and retry with exponential backoff.

---

### Requirement 13: Replay Workflow History

**User Story:** As a developer or operator, I want to replay the full event history of a workflow so that I can debug failures, test new agent logic, and reconstruct state after a disaster.

#### Acceptance Criteria

1. WHEN `GET /events?workflow_id={id}` is called without a `since` filter, THEN the system SHALL return all events for that workflow in ascending `timestamp` order.
2. WHEN the returned event list is passed to `project_state`, THEN the result SHALL equal the current materialized state for that workflow.
3. WHEN a workflow is replayed, THEN no new events SHALL be appended — replay is a read-only operation.
4. WHEN a workflow has zero events, THEN replay SHALL return an empty list and `project_state([])` SHALL return a `PENDING` state.
5. WHEN a workflow is replayed and the projected state differs from the materialized state, THEN the system SHALL log a consistency warning.

---

### Requirement 14: Error Handling

**User Story:** As a system operator, I want the system to handle invalid events, duplicate events, and MCP unavailability gracefully so that transient failures do not corrupt state or crash the system.

#### Acceptance Criteria

1. WHEN `EventService.append` receives an event with a missing required field, THEN it SHALL raise `EventValidationError` before any database write.
2. WHEN `EventService.append` receives an event whose `event_id` already exists in the `events` table, THEN it SHALL return the existing event record without inserting a duplicate — idempotent behavior.
3. WHEN the database is unavailable during `append_event`, THEN the system SHALL raise `MCPUnavailableError` and the caller SHALL retry with exponential backoff.
4. WHEN the database is unavailable during `get_events`, THEN the system SHALL raise `MCPUnavailableError`.
5. WHEN `EventService.append` receives an event with an unregistered `event_type`, THEN it SHALL raise `UnknownEventTypeError`.
6. WHEN a FastAPI route handler catches a domain exception, THEN it SHALL return the appropriate HTTP error code: `EventValidationError` → 422, `MCPUnavailableError` → 503, `UnknownEventTypeError` → 422, `CausationLoopError` → 422, `WorkflowConflictError` → 409.
7. WHEN an agent's `execute()` method raises an unhandled exception, THEN the agent SHALL catch it, log it, and emit `TASK_FAILED` with the error message in the payload.

---

### Requirement 15: Security Basics

**User Story:** As a system operator, I want basic security controls so that agents cannot impersonate each other and workflow IDs cannot be guessed by external parties.

#### Acceptance Criteria

1. WHEN a `POST /events` request is received, THEN the system SHALL validate that `source_agent` is a registered agent ID or `"orchestrator"` — unknown source agents SHALL be rejected with HTTP 422.
2. WHEN a `POST /workflows/start` request is received with a `workflow_id` that is not a valid UUID v4, THEN the system SHALL reject it with HTTP 422.
3. WHEN a `workflow_id` is generated by the system (if not provided by the client), THEN it SHALL be a UUID v4 generated with a cryptographically secure random source.
4. WHEN a `POST /events` request is received with a `target_agent` that is not a registered agent ID, THEN the system SHALL reject it with HTTP 422.
5. WHERE the agent registry is defined, THEN it SHALL be a static configuration loaded at startup — not a runtime-mutable list.
