---
description: AgentMesh Core implementation phases and delivery plan
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh Core Tasks

Follow the phased plan below when implementing the core system. The work is intentionally ordered to keep the project buildable and reviewable.

## Project phases

The implementation plan is organized by wave and phase:

- Wave 0: Phase 0 — Documentation and Portfolio Foundation
- Wave 1: Phase 1 — Project Bootstrap
- Wave 2: Phase 2 — Core Models
- Wave 3: Phase 3 — Storage
- Wave 4: Phase 4 — Event Service
- Wave 5: Phase 5 — State Service
- Wave 6: Phase 6 — API Routes
- Wave 7: Phase 7 — Orchestrator
- Wave 8: Phase 8 — Agents
- Wave 9: Phase 9 — End-to-End Workflow and Developer Experience
- Wave 10: Phase 11 — Local Agent Registry
- Wave 11: Phase 12 — Optional AWS Agent Registry Integration
- Wave 12: Phase 13 — Optional AgentCore Runtime Demo

## Phase 0: gate before implementation

- Stop after Phase 0 and request review before writing business logic.
- Create the required docs and hooks for learning, business problems, and medium-content backlog.
- Verify requirements, design, and task documents include the required documentation automation sections and quality gates.

## Phase 1: bootstrap

- Create the project folder structure under the repository's `src/agentmesh/` tree, matching the final architecture and deployment layout.
- Add `pyproject.toml` with pinned dependencies.
- Add Docker Compose, environment examples, configuration, and the FastAPI app scaffold.
- Implement a health endpoint and basic startup validation.
- Add pytest configuration and placeholders for tests.

## Phase 2: core models

- Add `src/core/models.py` with typed dataclasses and enums.
- Add `src/core/event_types.py` with all valid event types.
- Add `src/core/exceptions.py` with the event system exception hierarchy.
- Add validation helpers that enforce conversation, workflow, routing, and causation invariants.
- Add agent registry support with `orchestrator` as a valid built-in source.
- Cover models and validation with unit tests.

## Phase 3: storage

- Add SQLAlchemy ORM models for `events`, `current_state`, and `event_claims`.
- Build async database configuration and session dependency injection.
- Define repository interfaces and a concrete PostgreSQL implementation.
- Implement atomic `try_claim` logic with uniqueness enforcement.
- Generate and validate Alembic migrations.

## Phase 4: event service

- Implement idempotent event append and query flows.
- Enforce append-only semantics and causation loop protection.
- Validate inputs and domain rules before persistence.
- Add service-level tests for valid and invalid events.

## Phase 5: state service

- Implement deterministic state projection and cache update logic.
- Ensure state derives only from the event log.
- Add tests for projection determinism and edge cases.

## Phase 6: API routes

- Implement `events`, `state`, and `workflows` routes according to endpoint contracts.
- Keep routes thin and delegate to services.
- Add route tests for success and validation paths.

## Phase 7: orchestrator

- Build the workflow orchestrator as the central decision maker.
- Emit task events but never call agents directly.
- Enforce deterministic workflow progression and task assignment.

## Phase 8: agents

- Implement the agent polling loops and event routing behavior.
- Ensure each agent is stateless between cycles and stores required state only in events.
- Support `DIRECTED`, `FANOUT`, and `CLAIMED` routing modes.

## Phase 9: end-to-end workflow and DX

- Validate end-to-end workflow execution with the orchestrator and agents.
- Ensure local developer experience and testability are maintained.
- Keep the codebase consistent with observability and replayability goals.

## Later optional phases

- Local and AWS registry integrations
- Optional AgentCore runtime demo

## Execution rules

- Follow the phase ordering; do not skip ahead.
- Maintain the documentation quality gates defined in the design spec.
- Do not implement business logic before required documentation and bootstrap tasks are complete.
- Treat tests as part of the definition of done for each phase.
