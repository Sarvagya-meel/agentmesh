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
│   │   ├── Dockerfile.control-plane
│   │   └── Dockerfile.agent
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

```powershell
docker compose -f deployment/docker/compose.yml up --build
```

The compose stack keeps the `agentmesh` project name and runs a one-shot migration service before the control plane starts. That migration service applies SQL in `deployment/postgres/ddls/` and exits successfully once the schema is current.

## Agent entrypoints

```powershell
python -m agentmesh.agents.langgraph_copilot --worker
python -m agentmesh.agents.adk_spark --worker
```

The control plane is served from `agentmesh.services.agentmesh_server.app`; worker-specific code remains isolated to its concrete agent package.

## Validation

The repository validation workflow is:

```powershell
python -m pip install -e . --group local
python -m ruff check .
python -m mypy src
python -m pytest -q
```
