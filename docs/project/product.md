# AgentMesh — Product Overview

## What is AgentMesh?

AgentMesh is a **local-first, production-ready multi-agent framework** designed initially for job-search and email automation workflows, and built to scale into any future agentic use case.

The system is designed to run fully locally during development (via Docker Compose) and to be deployable to production infrastructure without architectural changes.

## Core Product Values

### 1. Traceability
Every durable action taken by the control plane, supervisor, or workers is recorded
as an immutable event. This means the full history of any workflow is available
for inspection, debugging, and auditing.

### 2. Replayability
Because state is a deterministic projection from the event log, any workflow can be replayed from scratch by re-processing its events. This enables:
- Debugging by replaying a failed workflow
- Testing new agent logic against historical event sequences
- Disaster recovery by rebuilding state from the event store

### 3. Controlled Orchestration
The independent supervisor makes structured planning and summary decisions, while
the durable control plane validates, queues, dispatches, retries, and records
workflow progress. Agents do not coordinate with each other directly; they receive
control-plane assignments.

### 4. Decentralized Event-Driven Collaboration
Agents collaborate through the Memory Control Plane (MCP) event bus, not through direct calls. This decoupling means:
- Agents can be added, removed, or replaced without changing other agents
- Agent failures are isolated and do not cascade
- The system can support fan-out, directed, and claimed routing patterns

## Primary Use Cases (v1)

- **Job Detection**: Scanning and identifying relevant job postings
- **Email Finding**: Locating contact emails for target companies/roles
- **Application Submission**: Automating or assisting with job application workflows

## Future Use Cases

AgentMesh is designed to be a general-purpose agentic framework. Future workflows may include:
- Research and summarization pipelines
- Customer support automation
- Data enrichment workflows
- Any multi-step, multi-agent process requiring auditability

## Design Philosophy

- **Events are the source of truth** — not in-memory state
- **Agents are stateless workers** — they execute authorized manifests and return structured results
- **The supervisor plans, the control plane dispatches** — planning is separate from queue ownership and worker execution
- **Observability is built-in** — not bolted on after the fact
