# AgentMesh Architecture

Follow `AGENTS.md` at the repository root as the single source of truth for AI
assistant instructions and architecture guardrails.

For local agent-runtime architecture, read `plan.md`, then
`PlanProblems&Decision.md`,
`agent_runtime/README.md`, `docs/agent-runtime-functional.md`,
`docs/agent-runtime-non-functional.md`, and `docs/agent-runtime-roadmap.md`.

When changing architecture, also inspect the active Markdown listed in the
Documentation Map in `AGENTS.md` so product, design, deployment, testing, and
assistant guidance stay aligned.

The production topology has one process per responsibility: `control-plane` owns
registry, events, claims, retries, and deterministic output validation;
`supervisor` owns planning, replan, summary, and LangGraph checkpoints; `litellm`
is the supervisor model gateway. Never import one service application to run it
inside another service process.
