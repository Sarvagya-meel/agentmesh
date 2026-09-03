# Agent Runtime Functional Design

This document explains what the local AgentMesh runtime does. Use it for future
planning, implementation handoff, and interview explanations. The authoritative
architecture is `plan.md`; this file should stay aligned with
`agent_runtime/README.md`.

## Actors

- User: starts direct agent work or multi-step workflows from Streamlit.
- Streamlit: thin client for Agent Playground direct `/invoke`, Agent Playground
  control-plane integration, and Workflow Playground.
- Registry/control plane: durable service that accepts requests, stores registry
  and workflow state, validates plans, queues work, leases work, retries work, and
  records events.
- Supervisor service: independent planning service that claims planning,
  validation, replan, and summary actions.
- Worker: agent runtime that exposes synchronous `/invoke` and executes immutable
  per-step manifests.
- QA/SDE roles: QA and supervisor may see hidden tests; SDE receives sanitized
  failure feedback.

## Request Flows

Direct Agent Playground work can call a ready agent `/invoke` endpoint and wait for
the response without creating durable workflow state. Durable direct work enters the
control plane asynchronously and is dispatched to a worker through leased queueing.

Workflow Playground work always enters the control plane asynchronously. The control
plane queues planning work, the supervisor claims it, and the supervisor submits a
validated plan version. After approval, the control plane dispatches ready steps to
workers and records each result.

## Planning And Replanning

Workflow and task reruns return a new durable workflow ID immediately. The control
plane records the parent IDs and approval policy, then queues normal supervisor
planning for that child. Repeating a rerun creates another child; it does not
reuse the source workflow or suppress a later user request. An explicit terminal
checkpoint cannot be recovered: the API rejects it before writing child events.
Use read-only replay to inspect terminal checkpoints, or choose a checkpoint with
an executable continuation for recovery.

The supervisor claims planning, validation, replan, and summary actions from the
control plane. It may inspect all authorized workflow outputs, but it must choose
exactly which fields each downstream worker receives.

Long planning tasks may pause on `planning.input_requested` and resume when the
control plane records `planning.input_provided` from supervison for checking the workflow progress(eg:role-advisor).

Semantic failures create checkpoint review or replan work. Replans create a new
`plan_version` instead of mutating historical workflow facts.

## Worker Manifests

Workers receive immutable per-step input manifests. A manifest includes:

- `workflow_id`
- `plan_version`
- stable `step_id`
- target agent identity
- named input bindings
- authorized upstream output fields
- retry and idempotency metadata

Workers return structured results to the control plane. They do not choose
downstream recipients, mutate the DAG, or call other agents.

## Dependency Model

Sequential and parallel dependencies are resolved by the control plane using
`workflow_id`, `plan_version`, stable `step_id`, and named input bindings. Parallel
completion order must not change the projected workflow result.

## Result Contract

The final user-facing result is recorded as `workflow.result` with
`source=supervisor` and `destination=user`.
