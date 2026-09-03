# AgentMesh — Testing Rules

## Guiding Principle

No feature is complete unless its tests pass. Tests are not optional and are not written after the fact—they are part of the definition of done for every component.

## Test Coverage Requirements

### Service Layer — Unit Tests

Every service class, control-plane queue component, and supervisor action handler
must have tests covering:
- Happy path for each public method
- Error and edge-case behavior
- Dependency injection with in-memory fakes or mocks

### API Layer — Route Tests

Every FastAPI route should be tested with httpx and ASGITransport, covering success and validation failures.

### State Projection — Deterministic Tests

The state projection algorithm must be tested to verify determinism and replay safety:
- Same sequence of events always produces the same state
- Replaying the full event log reproduces the materialized result
- Empty event logs produce a defined initial state

## Test Infrastructure Rules

- Use `pytest` and `pytest-asyncio`
- Keep fixtures small and explicit
- Run the full suite from the project root with `python -m pytest -q`
- CI must also run `ruff check .` and `mypy src`
- Validate both `control_plane_app:app` and `supervisor_app:app` as independent imports.
- Compose acceptance must inspect control-plane, supervisor, LiteLLM, migration, and
  worker logs, then repeat after project-scoped image and volume deletion.
