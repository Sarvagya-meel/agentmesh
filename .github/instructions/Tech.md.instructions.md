---
description: AgentMesh technology stack and dependency rules
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh — Technology Stack

This document summarizes the approved technologies, local infrastructure, and dependency rules for the project.

## Core runtime

- Python 3.11+
- FastAPI for web framework
- Uvicorn ASGI server
- SQLAlchemy (async) for ORM
- asyncpg as Postgres driver
- Alembic for migrations
- Pydantic v2 for validation
- PostgreSQL 15+ as the primary database

## Testing

- pytest, pytest-asyncio for async tests
- hypothesis for property-based tests
- httpx for async API testing

## Code quality

- ruff for linting/formatting
- mypy for static typing

## Local infrastructure

- Docker Compose for running PostgreSQL locally and reproducing the environment with `docker compose up`.
- No external services required in v1 (Redis/Kafka optional future integrations).

## Dependency rules

- Core services include FastAPI handlers, async SQLAlchemy sessions, Pydantic models, and service classes implementing domain logic.
- External LLM and tool integrations must be behind abstract interfaces (Protocols) and injected into consumers. Do not hardcode providers in core services or agents.
- Use mocks or fake providers in tests to avoid network calls.

## Version pinning and reproducibility

- Pin runtime dependencies in `requirements.txt` or `pyproject.toml` and use tooling (e.g., pip-compile) to manage transitive versions.
- Target Python 3.11 features only; avoid Python 3.12+ features without team agreement.

## Acceptance criteria

- All CI jobs must pass with pinned dependencies and reproducible builds.
- New external integrations must provide an abstract interface and a mockable implementation.
