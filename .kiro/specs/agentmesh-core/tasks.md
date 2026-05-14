# Implementation Plan: AgentMesh Core

## Overview

Implementation is broken into 10 sequential phases. Each phase must have passing tests before the next begins. Phase 1 bootstraps the project only — no business logic. Phases 2–9 build the system incrementally. Phase 10 adds developer tooling.

## Tasks

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["Phase 1: Project Bootstrap"]
    },
    {
      "wave": 2,
      "tasks": ["Phase 2: Core Models"]
    },
    {
      "wave": 3,
      "tasks": ["Phase 3: Storage"]
    },
    {
      "wave": 4,
      "tasks": ["Phase 4: Event Service"]
    },
    {
      "wave": 5,
      "tasks": ["Phase 5: State Service"]
    },
    {
      "wave": 6,
      "tasks": ["Phase 6: API Routes"]
    },
    {
      "wave": 7,
      "tasks": ["Phase 7: Orchestrator"]
    },
    {
      "wave": 8,
      "tasks": ["Phase 8: Agents"]
    },
    {
      "wave": 9,
      "tasks": ["Phase 9: End-to-End Workflow", "Phase 10: Developer Experience"]
    }
  ]
}
```

---

## Phase 1: Project Bootstrap

- [ ] 1. Create the full folder structure under `mcp/memory-server/src/` matching the spec exactly: `api/routes/`, `services/`, `storage/migrations/`, `agents/`, `core/`
- [ ] 2. Add `pyproject.toml` with pinned dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic>=2`, `pytest`, `pytest-asyncio`, `hypothesis`, `httpx`, `ruff`, `mypy`
- [ ] 3. Add `docker-compose.yml` with PostgreSQL 15 service, health check, named volume, and environment variables for `agentmesh` user/db
- [ ] 4. Add `.env.example` with `DATABASE_URL`, `APP_ENV`, `LOG_LEVEL`, and `POLL_INTERVAL_SECONDS`
- [ ] 5. Add `src/config.py` that reads environment variables using `pydantic-settings` `BaseSettings`; all settings must be typed
- [ ] 6. Add `src/main.py` with a FastAPI app, lifespan context manager for DB engine startup/shutdown, and include routers (stubs for now)
- [ ] 7. Add `GET /health` endpoint that returns `{"status": "ok"}` with HTTP 200
- [ ] 8. Verify the app starts with `uvicorn src.main:app` and `/health` returns 200
- [ ] 9. Add `pytest.ini` or `pyproject.toml` test config with `asyncio_mode = "auto"` and `testpaths = ["tests"]`
- [ ] 10. Add `tests/conftest.py` with placeholder fixtures (empty for now)
- [ ] 11. Write a test in `tests/api/test_health.py` that calls `GET /health` and asserts HTTP 200 and `{"status": "ok"}`

---

## Phase 2: Core Models

- [ ] 1. Add `src/core/models.py` with `RoutingMode` enum, `WorkflowStatus` enum, `Event` dataclass, `WorkflowState` dataclass, `Task` dataclass, `WorkflowContext` dataclass, `EventFilters` dataclass, and `WorkflowDecision` dataclass — all fields typed, all matching the design spec exactly
- [ ] 2. Add `src/core/event_types.py` with `EventType` enum covering all 11 event types and `REGISTERED_EVENT_TYPES` frozenset
- [ ] 3. Add `src/core/exceptions.py` with the full exception hierarchy: `AgentMeshError`, `EventValidationError`, `UnknownEventTypeError`, `UnknownAgentError`, `CausationLoopError`, `DuplicateEventError`, `MCPUnavailableError`, `WorkflowConflictError`, `WorkflowNotFoundError`, `ClaimConflictError`
- [ ] 4. Add validation helpers in `src/core/validation.py`: `validate_event(event: Event) -> None` that checks all required fields, validates `event_type` against registry, validates `routing_mode` constraints (DIRECTED requires `target_agent`, FANOUT/CLAIMED must not have `target_agent`), validates `routing_weights` are non-negative, validates `causation_chain` entries are valid UUIDs
- [ ] 5. Add `src/core/agent_registry.py` with `REGISTERED_AGENTS: frozenset[str]` loaded from config at startup; include `"orchestrator"` as a built-in valid source
- [ ] 6. Write unit tests in `tests/unit/core/test_models.py` covering: instantiation of all dataclasses with valid data, default field values, enum membership
- [ ] 7. Write unit tests in `tests/unit/core/test_validation.py` covering: valid event passes, missing `conversation_id` raises `EventValidationError`, missing `workflow_id` raises `EventValidationError`, unknown `event_type` raises `UnknownEventTypeError`, unknown `source_agent` raises `UnknownAgentError`, DIRECTED with no `target_agent` raises `EventValidationError`, FANOUT with `target_agent` raises `EventValidationError`, negative `routing_weight` raises `EventValidationError`, invalid UUID in `causation_chain` raises `EventValidationError`

---

## Phase 3: Storage

- [ ] 1. Add `src/storage/models.py` with `EventRow`, `CurrentStateRow`, and `EventClaimRow` SQLAlchemy ORM classes matching the design spec; include all indexes and the unique constraint on `event_claims(event_id)`
- [ ] 2. Add `src/storage/database.py` with async SQLAlchemy engine creation from `DATABASE_URL`, `AsyncSession` factory, and `get_session` async generator for FastAPI dependency injection
- [ ] 3. Add `src/storage/repository.py` with abstract base classes `EventRepository`, `StateRepository`, and `ClaimRepository` matching the design spec interfaces exactly
- [ ] 4. Add `src/storage/pg_repository.py` with concrete PostgreSQL implementations: `PgEventRepository`, `PgStateRepository`, `PgClaimRepository`; implement `try_claim` using `INSERT ... ON CONFLICT DO NOTHING` with row count check
- [ ] 5. Initialize Alembic in `src/storage/migrations/` with `alembic.ini` pointing to the async engine; set `target_metadata = Base.metadata`
- [ ] 6. Generate the initial Alembic migration that creates `events`, `current_state`, and `event_claims` tables with all columns, indexes, and constraints
- [ ] 7. Verify `alembic upgrade head` runs cleanly against a local PostgreSQL instance
- [ ] 8. Write unit tests in `tests/unit/storage/test_pg_repository.py` using an in-memory SQLite async engine (or a test PostgreSQL via `pytest-asyncio` fixtures): test `append` returns the event, test `append` with duplicate `event_id` returns existing event (idempotent), test `query` with `workflow_id` filter returns correct events, test `query` with `since` filter excludes older events, test `try_claim` returns `True` on first call, test `try_claim` returns `False` on second call for same `event_id`, test `upsert` creates and updates state correctly

---

## Phase 4: Event Service

- [ ] 1. Add `src/services/event_service.py` with `EventService` class that takes `EventRepository` and `StateService` via `__init__`
- [ ] 2. Implement `EventService.append(event: Event) -> Event`: call `validate_event`, check for duplicate `event_id` (return existing if found), assign `sequence_number` atomically, persist via repository, trigger `state_service.update_after_append`
- [ ] 3. Implement `EventService.query(filters: EventFilters) -> list[Event]`: delegate to repository with filters
- [ ] 4. Implement `EventService.replay(workflow_id: str) -> list[Event]`: return all events for workflow ordered by `sequence_number` ascending
- [ ] 5. Add exception handler wiring in `src/main.py`: map `EventValidationError` → 422, `MCPUnavailableError` → 503, `UnknownEventTypeError` → 422, `CausationLoopError` → 422, `WorkflowConflictError` → 409, `WorkflowNotFoundError` → 404
- [ ] 6. Write unit tests in `tests/unit/services/test_event_service.py` using a fake in-memory `EventRepository`: test happy path append returns event with `event_id`, test duplicate `event_id` returns existing event without second insert, test missing `conversation_id` raises `EventValidationError` before any repo call, test missing `workflow_id` raises `EventValidationError`, test unknown `event_type` raises `UnknownEventTypeError`, test unknown `source_agent` raises `UnknownAgentError`, test `query` delegates filters to repository, test `replay` returns events in sequence order

---

## Phase 5: State Service

- [ ] 1. Add `src/services/state_service.py` with `StateService` class that takes `EventRepository` and `StateRepository` via `__init__`
- [ ] 2. Implement `StateService.project(events: list[Event]) -> WorkflowState` as a pure function using `dataclasses.replace` and `match` statements; handle all 5 event types: `WORKFLOW_STARTED`, `TASK_ASSIGNED`, `TASK_COMPLETED`, `WORKFLOW_COMPLETED`, `WORKFLOW_FAILED`; return `PENDING` state for empty list
- [ ] 3. Implement `StateService.get_current(workflow_id: str) -> WorkflowState`: try materialized state first; if not found, replay events and project; raise `WorkflowNotFoundError` if no events exist
- [ ] 4. Implement `StateService.update_after_append(event: Event) -> None`: fetch current materialized state (or start from PENDING), apply the single new event incrementally, upsert the result
- [ ] 5. Write deterministic unit tests in `tests/unit/services/test_state_service.py`: test empty list returns PENDING state, test WORKFLOW_STARTED sets status=RUNNING, test TASK_ASSIGNED adds agent to assigned_agents and sets current_step, test TASK_COMPLETED adds to processed_event_types, test WORKFLOW_COMPLETED sets status=COMPLETED, test WORKFLOW_FAILED sets status=FAILED, test full sequence produces correct final state, test same input list always produces same output (called 3 times)
- [ ] 6. Write property-based tests in `tests/property/test_state_invariants.py` using `hypothesis`: test `project_state` is idempotent (same list → same result), test adding more events never removes `processed_event_types` entries (monotonicity), test every event in the list is reflected in the projected state, test `last_event_id` always equals the last event's `event_id`, test `workflow_id` and `conversation_id` are preserved through projection

---

## Phase 6: API Routes

- [ ] 1. Add `src/api/dependencies.py` with FastAPI `Depends` factories: `get_db_session`, `get_event_service`, `get_state_service`, `get_orchestrator_service`, `get_claim_repository`
- [ ] 2. Add `src/api/schemas.py` with all Pydantic v2 request/response models: `AppendEventRequest`, `EventResponse`, `StartWorkflowRequest`, `StartWorkflowResponse`, `WorkflowStateResponse`; include all field validators from the design spec
- [ ] 3. Implement `POST /events` in `src/api/routes/events.py`: validate body, call `event_service.append`, return `EventResponse` with HTTP 201
- [ ] 4. Implement `GET /events` in `src/api/routes/events.py`: parse query params into `EventFilters`, call `event_service.query`, return list of `EventResponse` with HTTP 200; reject missing `workflow_id` with 422
- [ ] 5. Implement `GET /state/{workflow_id}` in `src/api/routes/state.py`: call `state_service.get_current`, return `WorkflowStateResponse` with HTTP 200; return 404 if `WorkflowNotFoundError`
- [ ] 6. Implement `POST /workflows/start` in `src/api/routes/workflows.py`: validate body, call `orchestrator_service.start_workflow`, return `StartWorkflowResponse` with HTTP 201; return 409 if `WorkflowConflictError`
- [ ] 7. Register all routers in `src/main.py` with appropriate prefixes
- [ ] 8. Write API tests in `tests/api/test_events_routes.py` using `httpx.AsyncClient` with `ASGITransport`: test POST /events happy path returns 201 with event_id, test POST /events missing conversation_id returns 422, test POST /events missing workflow_id returns 422, test POST /events unknown event_type returns 422, test POST /events DIRECTED with no target_agent returns 422, test GET /events returns 200 with list, test GET /events without workflow_id returns 422, test GET /events with since filter returns only newer events
- [ ] 9. Write API tests in `tests/api/test_state_routes.py`: test GET /state/{workflow_id} returns 200 with correct state, test GET /state/{workflow_id} for unknown workflow returns 404
- [ ] 10. Write API tests in `tests/api/test_workflows_routes.py`: test POST /workflows/start returns 201 with workflow_id and status=RUNNING, test POST /workflows/start missing conversation_id returns 422, test POST /workflows/start invalid UUID workflow_id returns 422, test POST /workflows/start duplicate workflow_id returns 409

---

## Phase 7: Orchestrator

- [ ] 1. Add `src/services/orchestrator_service.py` with `OrchestratorService` class that takes `EventService` and `StateService` via `__init__`
- [ ] 2. Implement `OrchestratorService.start_workflow(context: WorkflowContext) -> str`: check for existing `WORKFLOW_STARTED` event (raise `WorkflowConflictError` if found), append `WORKFLOW_STARTED` event with `source_agent="orchestrator"`, return `workflow_id`
- [ ] 3. Implement `OrchestratorService.decide(state: WorkflowState) -> WorkflowDecision` as a pure deterministic function: if status is RUNNING and no agents assigned → assign `JobDetectorAgent`; if `JOB_DETECTED` in processed → assign `EmailFinderAgent`; if `EMAIL_FOUND` in processed → assign `ApplicationAgent`; if `APPLICATION_SENT` in processed → COMPLETE; if status is FAILED → FAIL; otherwise → WAIT
- [ ] 4. Implement `OrchestratorService.run_loop(workflow_id: str) -> None`: loop reading fresh state, calling `decide`, emitting the appropriate event, sleeping `POLL_INTERVAL`; stop on COMPLETED or FAILED
- [ ] 5. Write unit tests in `tests/unit/services/test_orchestrator_service.py` using fake `EventService` and `StateService`: test `start_workflow` appends WORKFLOW_STARTED and returns workflow_id, test `start_workflow` raises `WorkflowConflictError` if already started, test `decide` with RUNNING + no agents → ASSIGN_TASK for job-detector, test `decide` with JOB_DETECTED processed → ASSIGN_TASK for email-finder, test `decide` with EMAIL_FOUND processed → ASSIGN_TASK for applicator, test `decide` with APPLICATION_SENT processed → COMPLETE, test `decide` is deterministic (same state → same decision called 5 times)

---

## Phase 8: Agents

- [ ] 1. Add `src/agents/base.py` with abstract `BaseAgent` class: `agent_id: str`, `subscribed_event_types: list[str]`, abstract `execute(task: Task) -> TaskResult`, `emit_event(event_type, payload, causation_chain)` helper, `route_event(event)` that dispatches by routing mode, `run(workflow_id)` that runs the polling loop
- [ ] 2. Implement the four guards in `BaseAgent.run`: (1) subscription filter, (2) processed event type check via `StateService`, (3) pending event type check, (4) causation loop detection; emit `TASK_FAILED` with `reason: "recursion_loop_detected"` on guard 4 trigger
- [ ] 3. Implement `DIRECTED` routing in `BaseAgent.route_event`: only process if `event.target_agent == self.agent_id`
- [ ] 4. Implement `FANOUT` routing in `BaseAgent.route_event`: process if no `routing_weights`; if weights present, only process if this agent has the highest weight
- [ ] 5. Implement `CLAIMED` routing in `BaseAgent.route_event`: call `claim_repository.try_claim(event_id, agent_id)`; process only if claim succeeds; skip silently if claim fails
- [ ] 6. Add `src/agents/job_detector.py` with `JobDetectorAgent`: subscribes to `TASK_ASSIGNED` where `task_type=JOB_DETECT`; `execute` returns a stub `TaskResult` with `event_type=JOB_DETECTED` and sample payload; emits `JOB_DETECTED` on success, `TASK_FAILED` on error
- [ ] 7. Add `src/agents/email_finder.py` with `EmailFinderAgent`: subscribes to `TASK_ASSIGNED` where `task_type=EMAIL_FIND`; `execute` returns stub `TaskResult` with `event_type=EMAIL_FOUND`; emits `EMAIL_FOUND` on success, `TASK_FAILED` on error
- [ ] 8. Add `src/agents/applicator.py` with `ApplicationAgent`: subscribes to `TASK_ASSIGNED` where `task_type=APPLY`; `execute` returns stub `TaskResult` with `event_type=APPLICATION_SENT`; emits `APPLICATION_SENT` on success, `TASK_FAILED` on error
- [ ] 9. Write unit tests in `tests/unit/agents/test_base_agent.py`: test DIRECTED event addressed to this agent is processed, test DIRECTED event addressed to other agent is skipped, test FANOUT event with no weights is processed by all agents, test FANOUT event with weights only processes highest-weight agent, test CLAIMED event: first agent wins, second agent skips, test guard 4: agent_id in causation_chain emits TASK_FAILED and skips, test guard 2: already-processed event_type is skipped, test guard 3: event_type not in pending_event_types is skipped
- [ ] 10. Write unit tests in `tests/unit/agents/test_job_detector.py`, `test_email_finder.py`, `test_applicator.py`: test each agent's `execute` returns correct `TaskResult`, test each agent emits the correct result event, test each agent emits `TASK_FAILED` when `execute` raises

---

## Phase 9: End-to-End Workflow

- [ ] 1. Add `tests/conftest.py` fixtures for integration tests: async PostgreSQL session using a test database, `EventService`, `StateService`, `OrchestratorService`, and all three agents wired together
- [ ] 2. Write integration test `tests/integration/test_full_workflow.py`: start workflow → orchestrator emits TASK_ASSIGNED → JobDetectorAgent processes it → emits JOB_DETECTED → orchestrator emits next TASK_ASSIGNED → EmailFinderAgent processes → emits EMAIL_FOUND → orchestrator emits next TASK_ASSIGNED → ApplicationAgent processes → emits APPLICATION_SENT → orchestrator emits WORKFLOW_COMPLETED → assert final state is COMPLETED
- [ ] 3. Write replay test: after the full workflow completes, call `event_service.replay(workflow_id)`, pass the result to `state_service.project`, assert the projected state equals the materialized state
- [ ] 4. Write concurrent claim test in `tests/integration/test_claims.py`: append a CLAIMED event, launch 5 concurrent async tasks each attempting `try_claim` for the same `event_id`, assert exactly 1 returns `True` and 4 return `False`
- [ ] 5. Write idempotency test: append the same event twice (same `event_id`), assert the `events` table has exactly one row for that `event_id`, assert both calls return the same event record
- [ ] 6. Write loop prevention test: construct an event whose `causation_chain` contains the processing agent's `agent_id`, assert the agent emits `TASK_FAILED` with `reason: "recursion_loop_detected"` and does not call `execute`

---

## Phase 10: Developer Experience

- [ ] 1. Add `README.md` at the project root with: project overview, prerequisites (Python 3.11+, Docker), quickstart (`docker compose up -d`, `alembic upgrade head`, `uvicorn src.main:app`), environment variable reference, and architecture summary
- [ ] 2. Add `Makefile` with targets: `make up` (docker compose up), `make migrate` (alembic upgrade head), `make dev` (uvicorn with reload), `make test` (pytest), `make lint` (ruff check), `make typecheck` (mypy), `make all` (lint + typecheck + test)
- [ ] 3. Add `ruff.toml` or `[tool.ruff]` section in `pyproject.toml` with: `line-length = 100`, `select = ["E", "F", "I", "UP", "B"]`, `target-version = "py311"`
- [ ] 4. Add `mypy.ini` or `[tool.mypy]` section with: `python_version = "3.11"`, `strict = true`, `plugins = ["pydantic.mypy"]`
- [ ] 5. Add `docs/curl-examples.md` with sample curl commands for: POST /events, GET /events with filters, GET /state/{workflow_id}, POST /workflows/start
- [ ] 6. Verify `make all` passes with zero lint errors, zero mypy errors, and all tests green

## Notes

- **Phase 1 only** is implemented first. After Phase 1 passes, review before proceeding.
- Never skip tests. A phase is not complete until all its tests pass, `ruff` reports no lint errors, and `mypy` reports no type errors.
- Never introduce direct agent-to-agent calls at any phase.
- Never store workflow state only in memory — every state must be reconstructable from events.
- Redis Streams / Kafka are future extensions only. Do not introduce them in any phase.
- The `decide()` function in OrchestratorService is intentionally simple in v1. It will be replaced with a more sophisticated decision engine in a future spec.
- All LLM and external tool integrations must be behind abstract interfaces — never hardcoded into agent `execute()` methods.
