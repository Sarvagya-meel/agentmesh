# AgentMesh — Technology Stack

## Core Runtime

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.11+ |
| Web Framework | FastAPI | latest stable |
| ASGI Server | Uvicorn | latest stable |
| Validation | Pydantic | v2 |
| Database Driver | psycopg | latest stable |
| Orchestration | LangGraph | latest stable |
| Supervisor Gateway | LiteLLM Gateway | supervisor model calls only |
| Database | PostgreSQL | 15+ |
| UI | Streamlit | latest stable |

## Testing

| Tool | Purpose |
|------|---------|
| pytest | Test runner |
| pytest-asyncio | Async test support |
| ruff | Linting and formatting |
| mypy | Static type checking |
| httpx | API testing |

## Local Infrastructure

- Docker Compose is used to run PostgreSQL and local runtime services during development
- The deployment runtime is defined under `deployment/docker/` and `deployment/postgres/`
- The local setup must be reproducible with a single `docker compose -f deployment/docker/compose.yml up --build` command

## Dependency Rules

### What belongs in runtime dependencies
- FastAPI, Pydantic, HTTPX, and database clients for the shared runtime
- LangGraph for supervisor and worker graph execution where needed
- Google ADK and related model dependencies for the ADK worker
- Streamlit for the local UI

### What must be behind interfaces

External LLM integrations are accessed through abstract interfaces and injected
into consumers at construction time. Supervisor model calls go through LiteLLM
Gateway; worker model calls remain owned by worker runtime configuration. This
keeps runtime behavior testable and allows provider swaps without changing agent
logic.

## Version Pinning

`pyproject.toml` is the single dependency source of truth. PEP 735 groups define each deployable runtime and the combined local developer environment.
