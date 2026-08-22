# LangGraph Copilot Learning Log

This document records why the agent is designed as it is and which viable
alternatives were considered. Update it whenever a decision changes.

## Raw StateGraph Instead Of A Prebuilt Agent

**Decision:** Keep a typed `StateGraph` as the agent's core.

**Why:** AgentMesh requires explicit nodes, approval boundaries, audit events, and
deterministic orchestration behavior. A visible graph makes those transitions easier
to test and map to the workflow timeline.

**Alternatives:** `create_agent` would provide a faster tool-calling agent and useful
middleware defaults. The Functional API would reduce graph boilerplate. Either may
be preferable for a small standalone agent, but the explicit Graph API fits the
current control-plane and approval contracts better.

## Native Interrupts Instead Of An In-Memory Pending Dictionary

**Decision:** Use LangGraph `interrupt()` with a checkpointer and resume using
`Command(resume=...)`.

**Why:** The previous dictionary disappeared on process restart and was disconnected
from LangGraph's actual execution state. Native interrupts preserve the graph cursor,
support durable resumption, and expose pending state for debugging.

**Alternatives:** The orchestrator could store only the generated draft and approve it
without resuming the agent. That is simpler, but revision would start an unrelated run
and the agent would not truly own its output-review state.

## PostgreSQL Checkpoints In Deployed Environments

**Decision:** Use `MemorySaver` for isolated tests and PostgreSQL checkpoints for the
Docker runtime.

**Why:** PostgreSQL is already the local durable dependency and operational source of
truth. It avoids adding a second state service merely for graph checkpoints.

**Alternatives:** LangSmith Deployment can host the runtime and persistence. Redis is
useful for queues and short-lived coordination but is not the preferred durable graph
state store here. AgentCore remains a future deployment adapter.

## Framework-Owned Persistence Instead Of Service-Owned Factories

**Decision:** Organize persistence under `core/frameworks`. Every LangGraph component,
including the orchestrator and Copilot, uses `create_langgraph_checkpointer`. Google ADK
uses its native `SessionService` through `create_google_adk_session_service`.

**Why:** Persistence semantics belong to the framework executing the work. LangGraph
stores graph checkpoints and pending interrupts by thread ID, while ADK stores sessions,
events, and session state by application, user, and session ID. Keeping native types
preserves framework features and avoids duplicated factories named after current
deployment roles. Stable AgentMesh workflow/task IDs become stable ADK session IDs.

**Alternatives:** A single generic `create_persistence(framework)` function would have
an ambiguous return type and hide meaningful lifecycle differences. Service-specific
factories provide independent configuration but duplicate framework setup. Compatibility
wrappers remain temporarily for old imports while new code uses framework-owned paths.

## Separate Work Capabilities From Runtime Features

**Decision:** Advertise `CHAT`, `DRAFT`, and `REVIEW` as planner-visible capabilities;
publish LangGraph and approval support as Agent Card metadata.

**Why:** A planner should route work based on outcomes the agent can produce. Labels
such as `LANGGRAPH` and `HUMAN_IN_LOOP` describe implementation and policy, not tasks.

**Alternatives:** A future `APPROVAL_FACILITATION` capability may represent a real task
where the agent prepares or conducts an approval interaction. That should be added only
when the orchestrator can intentionally assign such a task.

## Platform-Owned Model Provider Contracts

**Decision:** Keep provider-neutral `TextCompletionClient` and
`StructuredOutputClient` protocols in `core/providers/contracts.py`, next to the
Groq adapter and provider factory. Concrete agents and the orchestrator depend on
these contracts rather than declaring their own model-client interfaces.

**Why:** Model access is expected to serve agents, orchestration, tools, MCP servers,
evaluation, and other platform components. Central contracts prevent each consumer
from inventing a slightly different interface while keeping provider-specific HTTP
logic outside agent code. Python protocols preserve structural typing, so Groq,
Gemini, future providers, and test fakes do not need to inherit a shared base class.

**Alternatives:** Keeping contracts under `agents/common` would make sense if only
agents called models. An abstract base class would enforce explicit inheritance but
would couple external adapters more tightly. A dedicated model-gateway package becomes
preferable later if AgentMesh adds provider routing, fallback, quotas, cost controls,
or centralized tracing.

## Separate Plan Approval And Agent Output Approval

**Decision:** The orchestrator owns workflow-plan approval. The LangGraph Copilot owns
approval of its generated output.

**Why:** Approving a plan answers whether the proposed work should run. Approving an
agent output answers whether a produced result is acceptable. Combining them makes the
audit trail ambiguous and prevents feedback on the actual draft.

**Alternatives:** One plan approval could authorize every output, which is efficient for
low-risk workflows. Both gates can be policy-controlled later so trusted workflows may
skip output review.

## Bounded Retry Instead Of Unrestricted Self-Correction

**Decision:** Retry transient model failures up to three attempts and cap human-driven
revisions at two by default.

**Why:** Bounded loops control latency and cost and guarantee termination. Validation,
authorization, and human rejection are not transient failures and must not be retried.

**Alternatives:** Evaluator-optimizer loops can improve high-value outputs, and model
fallback can improve availability. They belong behind explicit budgets and policies,
not in the first approval repair.

## Selective Agent Image Instead Of Copying All Source

**Decision:** Copy shared core/runtime code and only the selected concrete agent into
`Dockerfile.Agent`.

**Why:** This keeps deployment ownership clear, reduces accidental coupling, and proves
the agent can run independently from the control plane and UI.

**Alternatives:** A monolithic image is easier to build and may be acceptable for a
small internal prototype. Separate wheel artifacts would produce even cleaner images
and are a later packaging improvement.

## Hybrid Multi-Agent Patterns

**Decision:** Use a deterministic custom workflow as the backbone, a supervisor for
dynamic decomposition, a router for single or parallel specialist selection, and
handoffs only for user-facing transfers of control.

**Why:** No single multi-agent pattern fits workflow execution, background work,
parallel research, and conversational ownership equally well.

**Alternatives:** Treating every worker as a supervisor tool is simpler in-process but
does not match independently deployed agents. Pure handoffs are natural for chat but
weak for durable background assignments and leases.

## Lease-Based Presence Instead Of A Boolean Registration Flag

**Decision:** Give every running worker a unique runtime instance ID and report its
lifecycle state, active task count, start time, and latest successful model call in a
60-second heartbeat. Registry entries become stale after 180 seconds.

**Why:** Registration says that an agent exists; a renewable lease says that a specific
runtime is still able to work. The extra telemetry lets the orchestrator avoid degraded
or draining instances without turning routine heartbeats into noisy audit events.

**Alternatives:** Container health checks alone cannot prove registry connectivity or
worker progress. A Redis TTL key is a good high-scale presence mechanism, but PostgreSQL
and the existing registry are enough for the current deployment size.

## Durable Assignment Attempts And Dead Letters

**Decision:** Persist attempt number, retry schedule, error classification, idempotency
key, and dead-letter state with each assignment claim. Renew the claim lease while an
agent is working and retry only failures classified as transient.

**Why:** HTTP retries cannot recover a task after a worker crash and can publish a
duplicate terminal result. Durable attempts preserve history and give operators an
explicit place to inspect work that exhausted its retry budget.

**Alternatives:** Celery, Dramatiq, or a managed queue provide mature delivery and retry
semantics. They remain valid scaling options, but introducing one now would duplicate
the event-log and claim model before its boundaries are stable.

## Linked Reruns Instead Of Overwriting History

**Decision:** A workflow or task rerun creates a new workflow linked to the original.
Prior events and results remain immutable.

**Why:** Operators need to compare attempts and understand which input, agent, and
approval produced each result. Mutating the old workflow would erase that evidence.

**Alternatives:** Rewinding an existing LangGraph checkpoint is useful for low-level
node recovery. It is distinct from an operator-requested rerun and should not replace
the auditable linked-workflow operation.

## One Executor Per Process

**Decision:** Create one concrete agent and one `AgentExecutor` during process startup.
Direct requests and queued assignments share it in combined mode.

**Why:** One executor makes model clients, graph persistence, concurrency limits, and
shutdown ownership unambiguous. Per-thread locks prevent concurrent writes to one graph
thread while the process semaphore still allows unrelated conversations to overlap.

**Alternatives:** Separate API and worker agent objects simplify isolation but double
provider clients and can diverge in behavior. Always running split processes remain
available through the `api` and `worker` roles when independent scaling is needed.

## MessagesState For Multi-Turn State

**Decision:** Use `MessagesState` and its `add_messages` reducer with stable thread IDs.

**Why:** The reducer appends new turns, replaces messages with matching IDs, and retains
typed LangChain messages in checkpoints. Callers submit only the new turn; PostgreSQL
restores prior turns after restart.

**Alternatives:** A plain list reducer is smaller but duplicates messages during replay
and loses update semantics. Storing complete transcripts in each request increases
payload size and makes the caller responsible for authoritative history.

## Native Async Graph Execution

**Decision:** LangGraph agents use `ainvoke()` with `AsyncPostgresSaver`; synchronous
entry points remain test and compatibility paths only.

**Why:** FastAPI and the worker are asynchronous, so a native async saver avoids blocking
and supports concurrent thread IDs. A synchronous PostgreSQL saver cannot service
LangGraph's async checkpoint methods.

**Alternatives:** Running every graph call in a thread pool works for synchronous agents
but wastes threads around async I/O. A fully sync server would simplify persistence at
the cost of weaker concurrency and a second runtime model.

## Bounded Evaluator-Optimizer Loops

**Decision:** Feed low-scoring drafts back to generation under attempt, token, and
deadline limits.

**Why:** A score without a revision edge measures quality but cannot improve it. Three
independent budgets guarantee termination and expose why optimization stopped.

**Alternatives:** Always accepting the first draft is cheaper. Unbounded reflection may
improve some outputs but creates unpredictable latency, cost, and failure behavior.

## Deterministic Parallel Result Reduction

**Decision:** The supervisor reduces results by `(task_id, attempt_number)` and selects a
canonical value before sorting keys.

**Why:** The operation is associative, commutative, and idempotent, so retries and future
parallel completion order cannot change the projected workflow result.

**Alternatives:** Appending results preserves arrival order but duplicates retried writes
and makes output nondeterministic. Last-write-wins requires a trustworthy global clock.

## Opt-In Namespaced Store Memory

**Decision:** Long-term memory is disabled by default and requires explicit consent and
a user ID. Values are namespaced by agent and user, expire, can be deleted, and reject
credential-like data.

**Why:** Checkpoint state belongs to one execution; durable preferences cross executions
and therefore need separate consent, retention, and isolation rules. The supervisor
passes only approved preferences into planning and worker task context.

**Alternatives:** Saving every conversation automatically is convenient but creates
privacy and retention risk. A vector database may later support semantic recall, but it
does not remove the need for consent and namespace boundaries.

## Read-Only Replay And Diagnostic Forks

**Decision:** History and replay inspect checkpoints without executing side-effecting
nodes. Fork creates a separate thread/workflow namespace with source lineage.

**Why:** Re-invoking an orchestration checkpoint could emit duplicate assignments or
audit events. Read-only replay supports inspection, while an isolated fork supports
experimentation without mutating the source.

**Alternatives:** Native execution replay is appropriate only after every external side
effect has an idempotency contract. Copying state outside LangGraph would lose checkpoint
metadata and framework-native inspection.

## Tracing Is Explicitly Opt-In

**Decision:** Force LangSmith tracing off unless configuration enables it, and attach
agent, thread, workflow, task, assignment, run, and attempt metadata to graph runs.

**Why:** Local prompts must not leave the environment by surprise. When tracing is
enabled, stable identifiers make traces correlate with the PostgreSQL timeline.

**Alternatives:** Always-on hosted tracing is easier operationally but violates the local
data boundary. OpenTelemetry is a future vendor-neutral complement for service metrics.

## Offline Mermaid As A Checked Artifact

**Decision:** Export Mermaid source from compiled graphs and fail CI when committed
diagrams are stale.

**Why:** The diagram is reviewable without a rendering service and node-coverage tests
catch undocumented graph changes.

**Alternatives:** Runtime screenshots are friendlier to nontechnical readers but are
binary, harder to diff, and can become stale without a structural check.

## Future Decision Records

Add entries before implementing:

- parallel scheduling and reducer semantics
- tool-risk and approval policy
- MCP authorization and database access boundaries
- A2A task and artifact mapping
- A2UI component contract
- evaluation thresholds required for production release
