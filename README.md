# AgentMesh

AgentMesh is a hybrid multi-agent system that keeps workflow state in an append-only event log and derives current state deterministically from that history. The control plane coordinates orchestration; workers register, poll for assignments, and submit results through the shared event model.

## Final repository structure

```text
agentmesh/
├── .github/
├── .kiro/
├── deployment/
│   ├── docker/
│   │   ├── compose.yml
│   │   ├── Dockerfile.Service   # control-plane and UI images
│   │   ├── Dockerfile.Agent     # worker agent images
│   │   └── Dockerfile.Migrate   # one-shot schema migration image
│   ├── agentcore/
│   │   └── README.md
│   └── postgres/
│       ├── ddls/
│       ├── scripts/
│       └── README.md
├── docs/
├── scripts/
├── src/
│   └── agentmesh/
│       ├── agents/
│       ├── database/
│       │   └── postgres/
│       └── ...
├── tests/
├── .dockerignore
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## Dependency groups

The project uses PEP 735 groups in `pyproject.toml` as the source of truth for installable runtimes.

```powershell
python -m pip install --upgrade "pip>=25.1"
python -m pip install -e . --group local

# Control-plane image
python -m pip install --group control-plane

# LangGraph agent image
python -m pip install --group agent-langgraph

# ADK agent image
python -m pip install --group agent-adk
```

The dependency ownership is:

- `shared`: FastAPI, Uvicorn, Pydantic, pydantic-settings, python-dotenv, HTTPX, psycopg
- `langgraph-framework`: LangGraph
- `adk-framework`: Google ADK, LiteLLM, Google GenAI
- `postgres-checkpoint`: langgraph-checkpoint-postgres
- `ui-framework`: Streamlit
- `dev-tools`: pytest, pytest-asyncio, Ruff, mypy

## Local setup

```powershell
cd "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade "pip>=25.1"
python -m pip install -e . --group local
$env:PYTHONPATH = "src"
python scripts/run_local.py
```

The launcher starts the API and UI together. Health checks are exposed through the control plane.

## Docker and migration flow

Copy `.env.example` to `.env` and set at minimum `GROQ_API_KEY` before starting the stack:

```powershell
docker compose -f deployment/docker/compose.yml up --build
```

The compose stack (`agentmesh` project name) starts in dependency order:

1. **postgres** — PostgreSQL 15, health-checked
2. **migrate** (`Dockerfile.Migrate`) — one-shot container that applies all DDLs from `deployment/postgres/ddls/` and exits
3. **orchestrator-supervisor** (`Dockerfile.Service`, `DEPENDENCY_GROUP=control-plane`) — control plane + API on port 8000
4. **agent-langgraph-copilot** (`Dockerfile.Agent`, `AGENT_PACKAGE=agent_langgraph_copilot`) — LangGraph worker on port 8101
5. **agent-googleadk-chatagent** (`Dockerfile.Agent`, `AGENT_PACKAGE=agent_adk_spark`) — Google ADK worker on port 8102
6. **streamlit** (`Dockerfile.Service`, `DEPENDENCY_GROUP=local`) — UI on port 8501

LLM environment variables (`GROQ_API_KEY`, `GROQ_MODEL`, etc.) are defined once in the `x-llm-env` YAML anchor and merged into all services that need them.

## Agent entrypoints

```powershell
python -m agentmesh.agents.agent_langgraph_copilot --worker
python -m agentmesh.agents.agent_adk_spark --worker
```

The control plane is served from `agentmesh.services.service_agentmesh_server.app`; worker-specific code remains isolated to its concrete agent package.

## Validation

The repository validation workflow is:

```powershell
python -m pip install -e . --group local
python -m ruff check .
python -m mypy src
python -m pytest -q
```
