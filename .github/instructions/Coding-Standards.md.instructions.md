---
description: AgentMesh coding standards and developer guidelines
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh — Coding Standards

Follow these coding standards when authoring Python code in this repository. These rules are enforced by code review and automated tools (ruff, mypy) where possible.

## Core principles

- Use type hints everywhere: all parameters, return types, and class attributes must be annotated. Prefer `X | Y` for unions and avoid `Any` unless justified with a comment.
- Prefer dependency injection over module-level singletons. Services and agents receive dependencies via constructors or FastAPI `Depends()`.
- Keep Pydantic domain models separate from PostgreSQL row/DDL concerns. Repositories convert between layers.
- Workers must be stateless between polling cycles; persistent workflow state belongs in events and checkpoints.
- Keep functions small, pure where possible, and easy to test. Extract complex logic into named helpers.
- Do not put business logic in FastAPI route handlers — handlers should validate input, call services, and return responses only.
- Avoid global mutable state. Use FastAPI `lifespan` for startup/shutdown side effects.
- Add docstrings (Google-style) for core interfaces, public service methods, repository methods, and non-trivial algorithms.
- Use domain exceptions from `src/agentmesh/core/models/exceptions.py`; convert these to HTTP responses via FastAPI exception handlers.
- Use absolute imports, grouped: stdlib → third-party → local. Let `ruff` enforce ordering.
- Do not perform blocking I/O inside async route handlers or lifespan tasks.

## Examples and guidance

- Type hints:
  - Good: `async def append_event(event: Event) -> EventRecord:`
  - Bad: `async def append_event(event):`

- Dependency injection:
  - Good: `EventService(repo: EventRepository)`
  - Bad: creating repository instances inside methods using hidden globals

- Domain vs persistence:
  - Services and agents work with Pydantic models from `src/agentmesh/core/models.py`.
  - Storage repositories own SQL and convert database rows into domain models.

- Route handlers should not implement business logic; they must call services and return domain-mapped responses.

## Tooling and enforcement

- ruff for linting/formatting
- mypy for static typing (strict mode)
- CI must run linters and type checks on changed files

## Acceptance criteria for code changes

When submitting changes, ensure:
- Types are present and mypy passes for changed files
- ruff reports no new issues in changed files
- No hidden global mutable state is introduced
- Business logic remains in service layer, not route handlers
