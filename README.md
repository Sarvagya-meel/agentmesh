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
- LangGraph master orchestration with plan and per-task human approval gates
- Dynamic capability-based agent discovery with no hardcoded worker IDs
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
| Orchestration | LangGraph |
| Database | PostgreSQL 15 |
| Testing | pytest, pytest-asyncio, hypothesis |
| Linting | ruff |
| Type Checking | mypy |
| Local DB | Docker Compose |

---

## Project Status

The master orchestration and first complete worker path are implemented. A LangGraph coordinator discovers live agents, creates and validates a structured plan, pauses for plan and task approval, then emits directed assignments. Independent LangGraph and Google ADK workers heartbeat, poll, atomically lease assignments, call a real LLM, and submit claim-authenticated results. Expired leases allow a restarted worker to recover unfinished work.

---

## Quick Start

### 1) Create and activate the virtual environment

```powershell
cd "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

### 2) Start everything from a single entry point

```powershell
cd "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m agentmesh.local_entrypoint
```

This single command starts:
- the FastAPI API on http://127.0.0.1:8000
- the Streamlit chat UI on http://127.0.0.1:8501

If a service is already running, the launcher reuses it instead of crashing.

### 3) Health check

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/health
```

Expected JSON:

```json
{"status":"ok"}
```

### 4) Open the UI

Open this in a browser:

```text
http://127.0.0.1:8501
```

You should see a basic chat interface where the conversation agent is available and auto-registered with the registry.

---

## Master Orchestrator

The master orchestrator is a control-plane agent. It does not execute worker tools directly. Instead, it:

1. captures a snapshot of online agents from the dynamic registry
2. creates and validates a structured workflow plan
3. interrupts for plan approval, revision, or rejection
4. proposes each task and interrupts for a second approval
5. emits a directed `TASK_ASSIGNED` event only after approval
6. waits for the worker's external `TASK_COMPLETED` or `TASK_FAILED` result

```text
POST /workflows/start
GET  /workflows/{workflow_id}
POST /workflows/{workflow_id}/approvals
GET  /workers/{agent_id}/assignments
POST /workers/{agent_id}/assignments/{event_id}/claim
POST /workers/{agent_id}/assignments/{event_id}/result
GET  /events?workflow_id={workflow_id}
GET  /state/{workflow_id}
```

The Streamlit Workflow sidebar drives the same API and renders generic approval controls for any registered agent. Local development uses in-memory events and checkpoints by default. Set `EVENT_STORE_BACKEND=postgres` and `ORCHESTRATOR_CHECKPOINT_BACKEND=postgres` to retain both across restarts.

### Run the LLM agents

Run either framework by itself:

```powershell
python -m agentmesh.runners.run_langgraph_agent --prompt "Explain event sourcing"
python -m agentmesh.runners.run_google_adk_agent --prompt "Explain event sourcing"
```

Run them as independent polling workers before submitting workflows:

```powershell
python -m agentmesh.runners.run_langgraph_agent --worker
python -m agentmesh.runners.run_google_adk_agent --worker
```

Use `--worker --once` to process at most one assignment. Worker timing and API location are configured centrally with `AGENTMESH_API_URL`, `POLL_INTERVAL_SECONDS`, `WORKER_HEARTBEAT_SECONDS`, `WORKER_LEASE_SECONDS`, and `WORKER_REQUEST_TIMEOUT_SECONDS` in the ignored root `.env`.

The repeatable live matrix covers no-agent, LangGraph-only, Google-ADK-only, and all-agent workflows:

```powershell
python scripts\live_orchestration_smoke.py
```

### Groq planning brain

AgentMesh can replace the deterministic local planner with Groq `openai/gpt-oss-120b`. The model receives the user goal, human revision feedback, and a minimal snapshot of registered agent capabilities. It returns a strict JSON plan draft; AgentMesh generates task IDs and validates positions, dependencies, agent IDs, and advertised capabilities before requesting human approval.

All model settings live in the ignored repository-root `.env`:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your-key-from-the-groq-console
GROQ_MODEL=openai/gpt-oss-120b
GROQ_API_BASE=https://api.groq.com/openai/v1
GROQ_REASONING_EFFORT=medium
GROQ_TEMPERATURE=0.1
GROQ_MAX_COMPLETION_TOKENS=4096
GROQ_TIMEOUT_SECONDS=45
```

The real key belongs only in `.env`, which is ignored by Git. `.env.example` contains safe placeholders. Tests set `LLM_PROVIDER=mock` before application imports, so `pytest` never calls Groq or consumes quota.

---

## LangGraph Conversation Agent

```python
from agentmesh.agents.langgraph_copilot.agent import ConversationAgent

agent = ConversationAgent()
response = agent.run_conversation("Plan a launch for my product")
print(response["draft_reply"])
```

This version keeps the human-in-the-loop pattern explicit by separating the draft response from the approval check. The registry and the orchestrator can later route task requests to this agent using its Agent Card metadata.

---

## Dynamic Agent Registry

```python
from agentmesh.registry.models import AgentCard
from agentmesh.registry.repository import InMemoryRegistryRepository
from agentmesh.registry.service import RegistryService

service = RegistryService(InMemoryRegistryRepository())
service.register_agent(
    AgentCard(
        agent_id="langgraph-copilot",
        name="langgraph-copilot",
        capabilities=["CHAT", "REVIEW"],
        endpoint="http://localhost:8001",
    )
)
print(service.find_capable_agents("CHAT"))
```

This registry supports dynamic registration, heartbeats, capability matching, and later A2A discovery without hardcoding agent IDs.

### Registry API endpoints

```text
POST /registry/agents
GET /registry/agents
GET /registry/agents/{agent_id}
POST /registry/agents/{agent_id}/heartbeat
GET /registry/agents/capabilities/{capability}
```

Example registration payload:

```json
{
  "agent_id": "conversation-agent",
  "name": "langgraph-copilot",
  "version": "1.0.0",
  "description": "Handles conversations with human approval",
  "endpoint": "http://localhost:8001",
  "capabilities": ["CHAT", "REVIEW"],
  "skills": ["conversation"],
  "owner": "platform-team",
  "status": "online"
}
```

---

## Smallest Multi-Agent Orchestration

```python
from uuid import uuid4

from agentmesh.services.orchestrator_service import AgentStep, OrchestratorService

service = OrchestratorService(
    [
        AgentStep("detect_jobs", "JOB_DETECT", "job_detector", "Find relevant roles"),
        AgentStep("find_email", "EMAIL_FIND", "email_finder", "Find the contact email"),
        AgentStep("apply", "APPLY", "applicator", "Submit the application"),
    ]
)

state, events = service.start_workflow(
    "conversation-1",
    "Find and apply to a good software role",
    workflow_id=uuid4(),
)

print(state.status)
print([event.event_type for event in events])
print([event.target_agent for event in events if event.event_type == "TASK_ASSIGNED"])
```

This is intentionally small: one orchestrator, three agents, and an append-only event sequence. It is enough to validate the pattern before scaling to a production workflow engine.

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

## Manual Run Commands

```powershell
# API only
cd "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m uvicorn agentmesh.main:app --host 127.0.0.1 --port 8000 --reload

# Streamlit UI only
cd "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m streamlit run src\agentmesh\ui\streamlit_app.py --server.headless true --server.port 8501

# Local entrypoint (recommended)
cd "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m agentmesh.local_entrypoint
```

---

## Folder Structure

```
agentmesh/
├── src/
│   └── agentmesh/
│       ├── __init__.py
│       ├── main.py                  # FastAPI app entrypoint
│       ├── local_entrypoint.py      # Starts API + Streamlit UI together
│       ├── api/
│       │   ├── routes/
│       │   │   ├── events.py
│       │   │   ├── state.py
│       │   │   ├── workflows.py
│       │   │   └── registry.py
│       │   └── dependencies.py
│       ├── services/
│       │   ├── event_service.py
│       │   ├── orchestrator_service.py
│       │   └── state_service.py
│       ├── storage/
│       │   ├── models.py
│       │   └── repository.py
│       ├── agents/
│       │   ├── base.py
│       │   ├── langgraph_copilot/
│       │   │   ├── __init__.py
│       │   │   └── agent.py
│       │   ├── job_detector/
│       │   ├── email_finder/
│       │   └── applicator/
│       ├── ui/
│       │   ├── __init__.py
│       │   └── streamlit_app.py
│       ├── clients/
│       │   └── mcp_client.py
│       ├── runners/
│       │   ├── run_orchestrator.py
│       │   ├── run_job_detector.py
│       │   ├── run_email_finder.py
│       │   └── run_applicator.py
│       ├── registry/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── repository.py
│       │   └── service.py
│       ├── integrations/
│       │   ├── aws/
│       │   └── local/
│       └── core/
│           ├── __init__.py
│           ├── event_types.py
│           ├── exceptions.py
│           └── models.py
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   ├── learning/
│   ├── business/
│   └── content/
├── .kiro/
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── docker-compose.yml
├── README.md
└── .env.example
```

---

## Run Commands

```powershell
# Start the API only
python -m uvicorn agentmesh.main:app --host 127.0.0.1 --port 8000 --reload

# Start the Streamlit chat UI only
python -m streamlit run src\agentmesh\ui\streamlit_app.py --server.headless true --server.port 8501

# Start API + UI together (recommended)
python -m agentmesh.local_entrypoint

# Run implemented agents as independent worker processes
python -m agentmesh.runners.run_langgraph_agent --worker
python -m agentmesh.runners.run_google_adk_agent --worker
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

## Optional AWS AgentCore / Agent Registry Usage

AgentMesh is **local-first and free by default**. All core functionality runs on your machine with Docker Compose and a local PostgreSQL instance. No AWS account is required to develop, test, or run workflows.

AWS integrations are **disabled by default** and controlled entirely by environment flags.

| Feature | Default | When to enable |
|---------|---------|----------------|
| AWS Agent Registry | `false` | When you want centralised agent discovery/governance metadata |
| AgentCore Runtime | `false` | When you want to deploy a selected agent to AWS compute |
| Bedrock LLM | `mock` | When you want real LLM calls (requires AWS credentials + cost) |

**Rules:**
- Local mode always works without AWS credentials
- Unit tests never call AWS — all AWS clients are mockable interfaces
- AWS Agent Registry syncs only metadata (agent ID, capabilities, version) — never workflow events or payload logs
- AgentCore Runtime is optional compute for selected agents — AgentMesh MCP remains the event store
- If a cloud operation fails, the system logs the failure and continues in local mode
- Use AWS Budgets and Free Tier / credits before enabling cloud execution

To enable AWS features, set the relevant flags in your `.env` file and ensure your AWS credentials are configured (`aws configure` or environment variables).
