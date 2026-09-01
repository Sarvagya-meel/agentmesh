# Agent Runtime Roadmap

This roadmap tracks the documentation-level target for the local agent runtime.
Use `plan.md` as the authoritative architecture.

Pair this roadmap with `docs/agent-runtime-functional.md` and
`docs/agent-runtime-non-functional.md` so implementation planning keeps behavior
and quality constraints separate.

## Target Architecture

- Durable registry/control-plane service owns registry data, queueing, workflow
  state, events, retries, deterministic validation, and checkpoint mappings.
- Independent supervisor service claims planning, validation, replan, and summary
  actions from the control plane.
- LiteLLM Gateway is mandatory for supervisor model calls only.
- Workers expose synchronous `/invoke` and receive immutable per-step input
  manifests.
- Streamlit provides Agent Playground direct `/invoke`, Agent Playground
  control-plane integration, and Workflow Playground.

## Required Runtime Semantics

- All durable direct and workflow requests enter the control plane asynchronously.
- Sequential and parallel dependencies bind outputs by `workflow_id`,
  `plan_version`, stable `step_id`, and named input bindings.
- The supervisor can inspect all authorized workflow outputs while limiting exactly
  which fields downstream workers receive.
- Hidden QA tests remain visible only to supervisor and QA roles; SDE feedback is
  sanitized.
- Planning can pause on `planning.input_requested` and continue after
  `planning.input_provided`.
- The control plane retries transient 429, timeout, and 502-504 failures without
  disturbing the supervisor.
- Semantic failures route to checkpoint review or replan.
- The final `workflow.result` is emitted with `source=supervisor` and
  `destination=user`.

## Documentation Tasks

- Keep root and runtime README language aligned with this topology.
- Keep functional behavior in `docs/agent-runtime-functional.md`.
- Keep reliability, recovery, security, and operability constraints in
  `docs/agent-runtime-non-functional.md`.
- Keep deployment docs clear that PostgreSQL is the durable control-plane store.
- Keep assistant guidance concise and point agents to `plan.md` plus this summary
  instead of duplicating the full design.
- Do not update historical learning logs, old proposals, or generated sanity
  reports unless the user explicitly asks for archival edits.
