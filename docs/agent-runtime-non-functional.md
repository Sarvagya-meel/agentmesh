# Agent Runtime Non-Functional Design

This document explains the quality attributes the local AgentMesh runtime must
preserve. Use it for implementation reviews, future planning, and interview
discussion. The authoritative architecture is `plan.md`.

## Reliability

All durable direct and workflow requests enter the control plane asynchronously.
The control plane owns PostgreSQL queueing, leased dispatch, retry scheduling,
dead lettering, idempotency, DAG state, deterministic validation, append-only
events, and LangGraph checkpoint mappings.

Transient worker failures such as 429, timeouts, and 502-504 responses are retried
by the control plane without disturbing the supervisor.

## Recoverability

PostgreSQL is the durable recovery boundary for registry data, queues, claims,
workflow events, DAG state, retry state, and checkpoint mappings. A restarted
worker or supervisor should recover from persisted control-plane state rather than
from in-memory process state.

## Determinism

Workflow projections and validation must be deterministic. Given the same
workflow events, plan versions, step IDs, and named input bindings, the control
plane should derive the same ready work and user-visible state.

## Security And Visibility

The supervisor can inspect authorized workflow outputs to plan downstream work,
but each worker receives only the fields selected for its manifest. Hidden QA
tests are visible only to supervisor and QA roles. SDE-facing feedback must be
sanitized so it is actionable without exposing hidden tests.

## Service Isolation

The supervisor does not own queues or directly invoke workers. Workers do not
select downstream recipients or mutate DAG state. Agent packages should stay
focused on execution behavior, prompts, schemas, and tools.

## Provider Boundaries

LiteLLM Gateway is required for supervisor model calls only. Worker model calls
remain owned by each worker runtime and its provider configuration.

## Operability

Streamlit remains a thin client. The local environment should stay reproducible
through the documented Docker and Python commands. Documentation-only changes
should avoid runtime code, migrations, Docker changes, and unrelated generated
output.
