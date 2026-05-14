# AgentMesh

A production-grade hybrid multi-agent system for job-search automation and future agentic workflows.

AgentMesh combines centralized orchestration with decentralized event-driven agent collaboration. Every action is recorded as an immutable event. State is always reconstructable from the event log. Agents never call each other directly.

---

## What This Project Demonstrates

- Append-only event sourcing with deterministic state projection
- Hybrid orchestration: centralized Orchestrator + decentralized A2A agent events
- Atomic event claiming for exclusive task processing
- Causation chain tracking and loop prevention
- Full workflow replayability and observability
- Clean API → Service → Storage layering with FastAPI and PostgreSQL

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Web Framework | FastAPI |
| ASGI Server | Uvicorn |
| ORM | SQLAlchemy (async) |
| DB Driver | asyncpg |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Database | PostgreSQL 15 |
| Testing | pytest, pytest-asyncio, hypothesis |
| Linting | ruff |
| Type Checking | mypy |
| Local DB | Docker Compose |

---

## Project Status

Currently in Phase 1A — environment and folder bootstrap only.
No application logic has been implemented yet.

---

## Virtual Environment Setup

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

### Git Bash / macOS / Linux

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

---

## Install Dependencies

```bash
# Runtime dependencies only
pip install -r requirements.txt

# Runtime + development dependencies (recommended)
pip install -r requirements-dev.txt
```

---

## Folder Structure

```
agentmesh/
├── mcp/
│   └── memory-server/
│       └── src/
│           ├── api/
│           │   ├── routes/        # FastAPI route handlers (events, state, workflows)
│           │   └── dependencies.py
│           ├── services/          # Business logic (EventService, StateService, OrchestratorService)
│           ├── storage/           # ORM models, repositories, Alembic migrations
│           ├── agents/
│           │   ├── base.py        # Shared abstract BaseAgent
│           │   ├── job_detector/  # JobDetectorAgent package
│           │   ├── email_finder/  # EmailFinderAgent package
│           │   └── applicator/    # ApplicationAgent package
│           ├── clients/
│           │   └── mcp_client.py  # HTTP client for agents running as separate processes
│           ├── runners/           # Independent process entrypoints
│           ├── core/              # Domain models, event types, exceptions
│           └── main.py
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   ├── learning/                  # Interview learning notes
│   ├── business/                  # Business problem documentation
│   └── content/medium/            # Medium-ready content drafts
├── .kiro/
│   ├── specs/agentmesh-core/      # Requirements, design, tasks
│   ├── steering/                  # Project-wide coding rules
│   └── hooks/                     # Automation hooks
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── docker-compose.yml
```

---

## Agent Package Structure

Each agent is a Python package, not a single file. This allows each agent to grow independently, be tested in isolation, and be deployed as a separate process.

- `agent.py` — main agent class extending `BaseAgent`
- `schemas.py` — agent-specific input/output Pydantic models
- `tools.py` — external integrations behind abstract interfaces
- `prompts.py` — LLM prompts and templates (provider injected, never hardcoded)
- `config.py` — agent-specific settings loaded from environment

`runners/` contains independent process entrypoints. Each agent can be started as a standalone process via its runner, without starting the full MCP server.

`clients/mcp_client.py` is the HTTP client used by runners and independently deployed agents to communicate with MCP. Agents must not import the service layer directly when running as separate processes.

Agents must not directly import or call other agents. All agent collaboration happens through MCP events. Shared contracts (domain models, event types, exceptions) live in `core/`.

---

## Documentation Quality Gate

A task is not complete unless:

1. Tests pass, where applicable.
2. Technical learning is added to `docs/learning/INTERVIEW_LEARNING.md`.
3. Business value is added to `docs/business/BUSINESS_PROBLEMS.md` or explicitly marked technical-only.
4. Medium-ready content is created under `docs/content/medium/` or added to `backlog-short-posts.md`.
5. The task summary explains what changed.

---

## Phase Notes

- **Phase 0** — Documentation and portfolio foundation (complete)
- **Phase 1A** — Environment and folder bootstrap (in progress)
- **Phase 1B onwards** — Not started. No application logic implemented yet.
