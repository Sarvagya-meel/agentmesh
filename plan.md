# AgentMesh Local Agent Runtime Plan

This is the authoritative architecture plan for the local AgentMesh agent-runtime
work. Keep implementation, documentation, and IDE assistant guidance aligned with
this file. Use `docs/agent-runtime-functional.md` for behavior details and
`docs/agent-runtime-non-functional.md` for quality constraints.

## Architecture Decision

AgentMesh separates durable coordination from agent execution:

- Registry becomes a durable registry/control-plane service.
- Orchestrator becomes an independent supervisor agent.
- Workers stay independently deployable execution services.
- Streamlit stays a thin client.
- PostgreSQL is the durable local control-plane store.

## Request Entry

All durable direct and workflow requests enter the control plane asynchronously.
The only synchronous direct path is Agent Playground direct `/invoke`, which is
for immediate agent testing and does not create durable workflow state.

Streamlit has three surfaces:

- Agent Playground direct `/invoke`
- Agent Playground control-plane integration
- Workflow Playground

## Control-Plane Responsibilities

The control plane owns:

- registry data and runtime readiness
- PostgreSQL queueing
- leased dispatch and idempotency
- transient retries and dead letters
- workflow DAG state
- deterministic validation
- append-only workflow events
- LangGraph checkpoint mappings
- final result delivery to the user

Transient worker failures such as 429, timeouts, and 502-504 responses are retried
by the control plane without disturbing the supervisor.

## Supervisor Responsibilities

The supervisor service polls and claims planning, validation, replan, and summary
actions. LiteLLM Gateway is required for supervisor model calls only.

The supervisor may inspect all authorized workflow outputs, but it must select
exactly which fields each downstream worker receives. Long planning tasks may
pause on `planning.input_requested` and resume after `planning.input_provided`.

Semantic failures trigger checkpoint review or replan.

The final user-facing result is recorded as `workflow.result` with
`source=supervisor` and `destination=user`.

## Worker Responsibilities

Workers expose synchronous `/invoke` and receive immutable per-step input
manifests. A worker manifest includes:

- `workflow_id`
- `plan_version`
- stable `step_id`
- named input bindings
- authorized upstream output fields
- retry and idempotency metadata

Workers execute their assigned manifest and return structured results to the
control plane. Workers do not select downstream recipients, mutate DAG state, or
call other agents directly.

## Dependency Model

Sequential and parallel dependencies link outputs by `workflow_id`,
`plan_version`, stable `step_id`, and named input bindings. Parallel completion
order must not change the projected workflow result.



## Documentation Layout

- `AGENTS.md`: single source of truth for AI assistant behavior.
- `plan.md`: source of truth for this architecture.
- `docs/agent-runtime-functional.md`: functional behavior and request flows.
- `docs/agent-runtime-non-functional.md`: reliability, recovery, security,
  determinism, provider, and operability constraints.
- `docs/agent-runtime-roadmap.md`: planning and tracking notes.
- IDE adapter files should point to `AGENTS.md` and this plan instead of
  duplicating the architecture.
