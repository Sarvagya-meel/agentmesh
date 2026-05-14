# AgentMesh — Testing Rules

## Guiding Principle

No feature is complete unless its tests pass. Tests are not optional and are not written after the fact — they are part of the definition of done for every component.

---

## Test Coverage Requirements

### Service Layer — Unit Tests

Every service class must have unit tests covering:
- Happy path for each public method
- All error/exception paths
- Edge cases (empty inputs, boundary values, invalid states)

Services must be tested in isolation using dependency injection to replace storage with in-memory fakes or mocks. No real database connections in unit tests.

**Applies to**: `EventService`, `StateService`, `OrchestratorService`

### API Layer — Route Tests

Every FastAPI route must have integration tests covering:
- Successful request/response cycle with correct status codes
- Validation errors (missing fields, wrong types) returning 422
- Business logic errors returning appropriate 4xx codes
- Response schema conformance

Use `httpx.AsyncClient` with `ASGITransport` to test routes without a live server.

**Applies to**: all routes in `events.py`, `state.py`, `workflows.py`

### State Projection — Deterministic Tests

The state projection algorithm must be tested to verify determinism:
- Same sequence of events always produces the same state
- Order of events matters and is respected
- Replaying a full event log produces the same result as the materialized state
- Empty event log produces a well-defined initial state

These tests must not use mocks — they test the pure projection function directly.

### Event Append — Idempotency Tests

The event append operation must be tested for idempotency:
- Appending the same event twice (same `event_id`) must not create a duplicate
- The second append must either be a no-op or return the existing event
- Concurrent appends of the same event must result in exactly one record

### CLAIMED Routing — Exclusive Claim Tests

The atomic claim mechanism must be tested to verify:
- Only one agent can successfully claim a given event
- Concurrent claim attempts result in exactly one success and all others fail with a conflict error
- A claimed event is not returned to other agents polling for unclaimed events
- A failed claim does not corrupt the event or claim state

Use concurrent async tasks or threads to simulate race conditions in tests.

### Hypothesis Property Tests — State Projection Invariants

Property-based tests using `hypothesis` must verify the following invariants for state projection:

1. **Idempotency**: Projecting the same event list twice produces identical state
2. **Monotonicity**: Adding more events never removes information from state (state only grows or transitions forward)
3. **Completeness**: Every event in the log is reflected in the projected state
4. **No orphan state**: State always has a corresponding `workflow_id` in the event log
5. **Causation integrity**: No event in the projected state has a `causation_id` that does not exist in the event log

```python
from hypothesis import given, strategies as st

@given(st.lists(event_strategy(), min_size=0, max_size=50))
def test_projection_is_deterministic(events):
    state_a = project_state(events)
    state_b = project_state(events)
    assert state_a == state_b
```

---

## Test Organization

```
tests/
├── unit/
│   ├── services/
│   │   ├── test_event_service.py
│   │   ├── test_state_service.py
│   │   └── test_orchestrator_service.py
│   ├── agents/
│   │   ├── test_base_agent.py
│   │   ├── test_job_detector.py
│   │   ├── test_email_finder.py
│   │   └── test_applicator.py
│   └── core/
│       └── test_state_projection.py
├── api/
│   ├── test_events_routes.py
│   ├── test_state_routes.py
│   └── test_workflows_routes.py
├── property/
│   └── test_state_invariants.py
└── conftest.py
```

---

## Test Infrastructure Rules

- Use `pytest-asyncio` with `asyncio_mode = "auto"` for all async tests
- Use `pytest` fixtures for shared setup (database sessions, service instances, test data factories)
- Do not use `unittest.TestCase` — use plain `pytest` functions and fixtures
- All tests must be runnable with `pytest` from the project root
- CI must run all tests before any merge

---

## What "Tests Pass" Means

A feature is complete when:
1. All unit tests for affected services pass
2. All API route tests for affected endpoints pass
3. All property tests pass with at least 100 examples (Hypothesis default)
4. `mypy` reports no type errors in the changed files
5. `ruff` reports no lint errors in the changed files
