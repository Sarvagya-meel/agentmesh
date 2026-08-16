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
- Pydantic v2 for validation
- psycopg for PostgreSQL access
- PostgreSQL 15+ as the primary database
- LangGraph for orchestration graphs
- Streamlit for local UI work

## Testing

- pytest and pytest-asyncio for test execution
- ruff for linting and formatting
- mypy for static typing

## Local infrastructure

- Docker Compose for running PostgreSQL locally and reproducing the environment with `docker compose up`
- No external services required in v1 beyond PostgreSQL and the local agent runtime

## Dependency rules

- Dependencies are declared only in the PEP 735 groups in `pyproject.toml`
- Shared runtime dependencies live under `shared`
- Deployment-specific runtime groups are `control-plane`, `agent-langgraph`, and `agent-adk`
- Do not add requirements.txt or requirements-dev.txt files that duplicate the root dependency groups
- Keep external LLM and tool integrations behind abstract interfaces and inject them into consumers

## Version pinning and reproducibility

- Use the root `pyproject.toml` as the single dependency source of truth
- Prefer the named install groups for targeted rebuilds and image creation
- Keep Python 3.11-compatible code and avoid 3.12+ syntax without explicit team agreement
