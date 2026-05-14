# AgentMesh — Product Overview

## What is AgentMesh?

AgentMesh is a **local-first, production-ready multi-agent framework** designed initially for job-search and email automation workflows, and built to scale into any future agentic use case.

The system is designed to run fully locally during development (via Docker Compose) and to be deployable to production infrastructure without architectural changes.

## Core Product Values

### 1. Traceability
Every action taken by any agent or orchestrator is recorded as an immutable event. Nothing happens outside the event log. This means the full history of any workflow is always available for inspection, debugging, and auditing.

### 2. Replayability
Because state is a deterministic projection from the event log, any workflow can be replayed from scratch by re-processing its events. This enables:
- Debugging by replaying a failed workflow
- Testing new agent logic against historical event sequences
- Disaster recovery by rebuilding state from the event store

### 3. Controlled Orchestration
The Orchestrator is the only component that makes structured workflow decisions. It decides what happens next in a workflow and emits task events accordingly. Agents do not coordinate with each other directly — they only respond to events assigned to them.

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

- **Events are the source of truth** — not in-memory state, not database rows
- **Agents are stateless workers** — they read events, do work, emit events
- **The Orchestrator is a coordinator, not a controller** — it guides workflows but does not execute tasks
- **Observability is built-in** — not bolted on after the fact
