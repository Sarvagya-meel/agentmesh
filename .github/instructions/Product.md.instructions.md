---
description: AgentMesh product overview, values, and use-cases
applyTo: "**/*.py, **/*.md, **/*.yml, **/*.yaml"
---

# AgentMesh — Product Overview

This file captures the product intent and design philosophy that should guide implementation and prioritization.

## What is AgentMesh?

AgentMesh is a local-first, production-ready multi-agent framework initially focused on job-search and email automation workflows. The architecture supports running locally (Docker Compose) and deploying to production without structural changes.

## Core product values

- Traceability: every action is an immutable event in the event log for auditing and debugging.
- Replayability: deterministic state projection enables replaying workflows for debugging, testing, and recovery.
- Controlled orchestration: the Orchestrator makes structured workflow decisions and emits task events; agents respond to events and do not coordinate directly.
- Decentralized event-driven collaboration: agents communicate through the MCP event bus enabling independent development and failure isolation.

## Primary v1 use cases

- Job Detection: discovering relevant job postings
- Email Finding: locating contact emails for targets
- Application Submission: automating parts of the application process

## Future possibilities

- Research/summarization pipelines, customer support automation, data enrichment, and other multi-step agentic workflows.

## Design philosophy (summary)

- Events are the source of truth; agents are stateless workers; the orchestrator coordinates, not controls; observability is first-class.

## How product guidance maps to engineering decisions

- Feature work must preserve event-sourcing guarantees and deterministic projections.
- Add agents and providers behind interfaces to allow swapping and testing.
- Prioritize observability and replayability when designing new workflow steps.
