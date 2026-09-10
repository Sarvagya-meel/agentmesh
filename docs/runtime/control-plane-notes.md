# Agent Runtime Control Plane

Follow `AGENTS.md` at the repository root as the single source of truth for
AgentMesh assistant instructions. Do not duplicate architecture rules here.

For local agent-runtime architecture, read `plan.md`, then
`docs/planning/plan-problems-and-decisions.md`,
`docs/runtime/overview.md`, `docs/runtime/functional.md`,
`docs/runtime/non-functional.md`, and `docs/runtime/roadmap.md`.

Supervisor writes cross the process boundary as `SUPERVISOR_ACTION_REQUESTED`
events and renewable claims. Worker outputs must be persisted and validated before
the supervisor can advance a checkpoint. Provider rate limits stay in the relevant
control-plane claim retry loop and must not restart the supervisor graph.
