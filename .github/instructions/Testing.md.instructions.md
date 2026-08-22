---
description: AgentMesh testing rules, organization, and acceptance criteria
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh — Testing Rules

Tests are part of the definition of done. Follow these rules when adding features or fixing bugs.

## Guiding principle

No feature is complete unless its tests pass. Tests are written as part of the change, not after.

## Test requirements

Service layer (unit tests):
- Cover happy paths, error paths, and edge cases for each public method.
- Test services in isolation with dependency injection (no real DB in unit tests).
- Applies to: EventService, StateService, WorkerService, and MasterOrchestratorAgent.

API layer (route tests):
- Integration tests must cover successful responses, validation errors (422), business errors (4xx), and response schema conformance.
- Use httpx.AsyncClient with ASGITransport to test routes without a live server.

State projection tests:
- Verify determinism: same event sequence → same state.
- Replaying the event log must match materialized state.
- Empty logs produce a well-defined initial state.

Event append tests:
- Append idempotency: appending the same event twice must not duplicate records.
- Concurrent appends result in a single record.

CLAIMED routing tests:
- Verify only one agent can claim an event under concurrent attempts.
- Use concurrent async tasks to simulate race conditions.

## Test organization

Follow the repository's test layout under `tests/` and keep fixtures close to the code they exercise. Avoid `unittest.TestCase` in favor of pytest functions and fixtures.

## Test infrastructure rules

- Use pytest-asyncio with `asyncio_mode = "auto"`.
- CI must run all tests and enforce type checking (mypy) and linting (ruff).

## Acceptance criteria for feature completion

A feature is complete when:
1. All relevant unit and route tests pass.
2. `mypy` reports no type errors in the changed files.
3. `ruff` reports no lint errors in the changed files.
