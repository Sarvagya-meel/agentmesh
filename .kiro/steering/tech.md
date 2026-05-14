# AgentMesh — Technology Stack

## Core Runtime

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.11+ |
| Web Framework | FastAPI | latest stable |
| ASGI Server | Uvicorn | latest stable |
| ORM | SQLAlchemy (async) | 2.x |
| DB Driver | asyncpg | latest stable |
| Migrations | Alembic | latest stable |
| Data Validation | Pydantic | v2 |
| Database | PostgreSQL | 15+ |

## Testing

| Tool | Purpose |
|------|---------|
| pytest | Test runner |
| pytest-asyncio | Async test support |
| hypothesis | Property-based testing |
| httpx | Async HTTP client for API tests |

## Code Quality

| Tool | Purpose |
|------|---------|
| ruff | Linting and formatting |
| mypy | Static type checking |

## Local Infrastructure

- **Docker Compose** is used to run PostgreSQL locally during development
- No external services (Redis, Kafka, etc.) are required in v1
- The local setup must be reproducible with a single `docker compose up` command

## Dependency Rules

### What belongs in core services
- FastAPI route handlers
- SQLAlchemy async sessions
- Pydantic models for request/response validation
- Domain logic in service classes

### What must be behind interfaces

**External LLM integrations** (e.g., OpenAI, Anthropic, local models) must be accessed through an abstract interface, never hardcoded into core services or agents. Example:

```python
class LLMProvider(Protocol):
    async def complete(self, prompt: str, **kwargs) -> str: ...
```

**External tool integrations** (e.g., web scrapers, email APIs, job board APIs) must similarly be behind abstract interfaces injected into agents at construction time.

This ensures:
- Core services remain testable without real LLM/API calls
- Providers can be swapped without changing agent logic
- Mock implementations can be injected in tests

## Version Pinning

All dependencies must be pinned to exact versions in `requirements.txt` or `pyproject.toml` to ensure reproducible builds. Use `pip-compile` or equivalent to manage transitive dependencies.

## Python Version Enforcement

The project targets Python 3.11+ and may use:
- `match` statements for pattern matching
- `tomllib` from stdlib
- `ExceptionGroup` and `except*`
- `Self` type from `typing`
- `TypeAlias` and `ParamSpec`

Do not use syntax or stdlib features that require Python 3.12+ without explicit team agreement.
