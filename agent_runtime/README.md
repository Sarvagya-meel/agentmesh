# Agent Runtime Architecture

This folder documents the local agent-runtime architecture. The authoritative
design is the repository root `plan.md`; keep this README as the operating
summary and update it when that design changes.

For deeper planning and interview explanations, use:

- `docs/agent-runtime-functional.md` for actors, request flows, manifests, and
  result contracts
- `docs/agent-runtime-non-functional.md` for reliability, recovery, determinism,
  security, and operability constraints

## Service Topology

- The registry is a durable registry/control-plane service, not an in-memory
  helper owned by the supervisor.
- The orchestrator is promoted to an independent supervisor service. It polls and
  claims planning, validation, replan, and summary actions from the control plane.
- LiteLLM Gateway is required for supervisor model calls only. Worker model calls
  remain owned by the worker runtime and its configuration.
- Streamlit stays a thin client with three surfaces: Agent Playground direct
  `/invoke`, Agent Playground control-plane integration, and Workflow Playground.

## Control-Plane Ownership

All durable direct and workflow requests enter the control plane asynchronously.
The control plane owns:

- PostgreSQL queueing and leased dispatch
- retry scheduling, dead lettering, and idempotency
- DAG state, plan versions, and deterministic validation
- append-only events and workflow projections
- LangGraph checkpoint mappings for supervisor review, replay, and resume
- final result delivery to the user

Transient execution errors such as 429, timeouts, and 502-504 responses are retried
by the control plane without waking or perturbing the supervisor. Semantic failures
trigger checkpoint review or a replan action.

## Supervisor Boundaries

The supervisor may inspect all authorized workflow outputs, but it must plan
exactly which fields each downstream worker receives. It does not directly invoke
workers, mutate queues, or bypass deterministic validation. Long planning tasks may
pause by emitting `planning.input_requested` and resume when the control plane
records `planning.input_provided`.

The terminal user-facing result is always recorded as `workflow.result` with
`source=supervisor` and `destination=user`.

## Worker Contract

Workers expose synchronous `/invoke` and receive immutable per-step input
manifests. A manifest is the worker's complete authorized view of the step:

- `workflow_id`
- `plan_version`
- stable `step_id`
- named input bindings
- authorized upstream output fields
- retry and idempotency metadata

Sequential and parallel dependencies link outputs by `workflow_id`, `plan_version`,
stable `step_id`, and named input bindings. Workers return structured results to the
control plane; they do not select downstream recipients.
