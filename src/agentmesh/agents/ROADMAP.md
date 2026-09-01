# AgentMesh LangGraph Capability Roadmap

This roadmap orders LangGraph work by delivery priority. It applies to every
LangGraph-based AgentMesh component unless a row names a narrower owner.

## Delivery Rules

- Build shared framework primitives under `core/frameworks/langgraph`.
- Keep agent-specific reasoning and state fields inside the owning agent package.
- Add a decision and alternatives entry to the owning `LEARNING.md` with every item.
- Keep capabilities opt-in when they transmit data outside the local environment.
- Finish tests, static checks, Docker build, and a restart/recovery test before moving
  an item to done.

## P1: Now

| Order | Capability | Owner | Action | Acceptance criteria | Status |
|---:|---|---|---|---|---|
| 1 | `MessagesState` and `add_messages` | All LangGraph agents | Replace plain string message lists with LangChain messages and an ID-aware reducer. | New messages append, same-ID messages update, and checkpoints deserialize messages correctly. | Done |
| 2 | Real multi-turn message memory | All LangGraph agents | Reuse a stable thread ID and submit only the new turn while checkpoint state retains history. | A second turn can use the first turn without resending it; restart with PostgreSQL retains the conversation. | Done |
| 3 | `ainvoke()` | All LangGraph agents | Add async task and workflow entry points while preserving synchronous worker compatibility. | Async and sync results have the same contract; concurrent thread IDs do not block one another. | Done |
| 4 | Evaluator-optimizer loop | All LangGraph agents | Route low-scoring output back to generation with feedback and strict iteration, token, and deadline budgets. | Low-quality output revises; good output exits; every loop terminates and exposes attempts. | Done |
| 5 | Parallel-result reducers | Control plane and supervisor | Add deterministic, associative reducers keyed by task/attempt ID. | Duplicate writes are idempotent and completion order cannot change the projected result. | Done |
| 6 | Long-term Store memory | All LangGraph agents | Add an injected LangGraph Store with explicit user namespace, consent, retention, and delete controls. | Memory is isolated per user, opt-in, durable in PostgreSQL, and never stores credentials. | Done |
| 7 | Checkpoint replay/time travel | All LangGraph agents | Expose checkpoint history, replay, and fork operations with audit lineage. | Operators can inspect and fork a checkpoint without mutating the original run. | Done |
| 8 | LangSmith tracing/evaluation | All LangGraph agents | Add disabled-by-default tracing metadata and deterministic evaluation suites. | Local runs send no traces by default; enabled traces include workflow/task/run IDs; evaluation gates run in CI. | Done |
| 9 | Graph visualization | All LangGraph agents | Export Mermaid source from compiled graphs and expose it through a read-only endpoint/CLI. | Diagrams build offline, match graph nodes, and require no live rendering service. | Done |

## P2: Next

| Order | Capability | Owner | Action | Acceptance criteria | Status |
|---:|---|---|---|---|---|
| 1 | Subgraphs | All LangGraph agents | Extract bounded planning, evaluation, and approval flows into reusable subgraphs. | Parent/subgraph checkpoint namespaces and interrupts resume correctly. | Planned |
| 2 | Parallel fan-out | Control plane and supervisor | Dispatch dependency-ready independent tasks concurrently and gather them through P1 reducers. | Independent tasks overlap, dependencies block correctly, and final order is deterministic. | Planned |
| 3 | Runtime context and per-run dependencies | All LangGraph agents | Define typed runtime context for identity, scopes, deadline, model, allowed tools, and policy. | Nodes receive dependencies without storing secrets in graph state or checkpoints. | Planned |

## P3: Future Capability

| Order | Capability | Owner | Action | Acceptance criteria | Status |
|---:|---|---|---|---|---|
| 1 | Tool calling and `ToolNode` | All LangGraph agents | Add schema-validated, policy-filtered tools and explicit tool routing. | Unauthorized calls fail closed; side effects are idempotent and audited. | Planned |
| 2 | MCP tools inside graphs | All LangGraph agents | Adapt approved MCP tools into the tool registry without passing broad credentials. | MCP authorization is audience-bound and PostgreSQL access starts read-only/allowlisted. | Planned |
| 3 | Token/state streaming and `astream()` | All LangGraph agents | Stream model tokens, state changes, progress, and interrupts through a versioned transport. | Slow clients, cancellation, reconnect, and terminal-event ordering are tested. | Planned |

## P1 Completion Evidence

- Copilot and supervisor use `MessagesState`, `add_messages`, and native async graph APIs.
- Docker uses `AsyncPostgresSaver`; synchronous savers remain isolated test compatibility.
- Stable threads survive process restart and pending output approvals resume correctly.
- Evaluator loops terminate under attempt, token, and deadline budgets.
- Supervisor task results use a deterministic task/attempt reducer.
- Store memory is opt-in, user-namespaced, retention-aware, deletable, and credential-safe.
- Checkpoint history, replay, and fork operations preserve the source execution.
- LangSmith is disabled by default and the quality workflow runs deterministic tests.
- Offline Mermaid files and read-only endpoints cover both compiled graphs.

P2 is now the active next phase. P3 tools and streaming do not enter the graph until
runtime scopes, approval policy, and audit contracts exist.
