# Supervisor and Registry Implementation Decisions

## Purpose

This record explains the decisions and problems encountered while beginning the
implementation of `plan.md` on `feature/Supervisor&RegistryPro`. It complements
the target architecture in `plan.md`; it is not a replacement for that plan.

Implementation baseline: commit `427ccb29`.

## Delivered In This Tranche

- Independent control-plane and supervisor FastAPI processes and Docker images.
- Durable supervisor actions represented in the existing Postgres event log.
- Lease-based action claim, renewal, completion, failure, and retry behavior.
- HTTP-only communication from the supervisor process to the control plane.
- Control-plane validation before a worker result is accepted for orchestration.
- Stable workflow, plan, step-position, dependency, and resolved-input context.
- Dependency-scoped worker inputs; workers do not browse the complete event log.
- LangGraph Postgres checkpoints owned by the supervisor process.
- LiteLLM proxy service and optional model routing for workers and supervisor.
- LangSmith tracing disabled by default, redacted, low-noise, and isolated from
  workflow state when tracing fails.
- Backward-compatible combined application for existing callers during rollout.
- DDL `007_supervisor_control_plane.sql`, unit tests, Docker operations guidance,
  Kiro steering updates, VS Code settings, and end-to-end sanity checks.

This is the first executable vertical slice of `plan.md`, not the completion of
every phase. The remaining work is listed below so that a green build is not
mistaken for full product completion.

## Architectural Decisions

### 1. Postgres events are the durable command source

Supervisor commands use `supervisor.action_requested` events instead of adding a
second unrelated queue table. A claim lease provides exclusive processing, while
completion and failure events preserve the full history. This keeps commands and
workflow facts in one replayable chronology and reuses established repository
semantics.

Consequence: event payloads and idempotency keys are contracts. They must be
versioned carefully, and projections must ignore terminal action events when
looking for pending work.

### 2. The control plane owns authoritative workflow state

Public requests, worker outputs, validation decisions, retries, and final results
pass through the control plane. The supervisor can reason over authorized events,
but it cannot write directly to workflow tables. Workers only receive an immutable
task payload and return a result to the control plane.

Consequence: a supervisor restart cannot skip validation or bypass event ordering.

### 3. The supervisor owns reasoning checkpoints

LangGraph checkpointers and stores live in the independent supervisor service.
Checkpoint identity is correlated with workflow and action identity. The control
plane remains usable when optional LangGraph imports are unavailable.

Consequence: checkpoint recovery restores reasoning progress, while Postgres
events remain the authority for externally visible workflow state.

### 4. Worker output is provisional until validated

Worker results first create `task.output_received`, then validation-requested and
validation-completed events. Only accepted output is passed back to orchestration.
The validator hashes output for idempotency and rejects empty, failed, or
unsupported statuses. `AWAITING_APPROVAL` is valid because it is a durable worker
result with a continuation thread, not an execution failure.

Consequence: validation may be retried without running the worker again, and the
same assignment cannot be accepted twice under different event identities.

### 5. Data lineage is explicit and dependency scoped

Every dispatched task includes `workflow_id`, `plan_id`, `plan_version`, step
position, dependency IDs, and resolved inputs keyed by stable aliases such as
`step_1`. Missing or unvalidated dependencies block dispatch. A worker receives
only declared dependency output, so an SDE worker does not receive hidden QA test
cases unless the plan explicitly permits that binding.

Consequence: completion order does not define input meaning. This contract also
supports future parallel fan-out even though the current orchestrator executes its
generated steps serially.

### 6. Infrastructure retries do not interrupt supervision

Rate limits, provider timeouts, connection resets, and similar temporary failures
are classified by the supervisor runner. The failed action is recorded and the
control plane schedules another attempt with a stable idempotency key and bounded
backoff. The supervisor process remains alive and can claim unrelated work.

Consequence: business replanning is separate from transport retry. Permanent
input or validation errors are returned for supervisor correction instead of
being retried unchanged.

### 7. Stable idempotency keys describe the request, not its latest event

Workflow start uses the workflow ID. Approval uses approval ID plus decision.
Task-result processing uses assignment identity. This prevents repeated polling
or a newly appended completion event from creating a logically duplicate command.

### 8. LiteLLM is an optional gateway boundary

Supervisor and worker clients can route through the local LiteLLM OpenAI-compatible
endpoint. Direct provider configuration remains available for staged rollout. The
Docker image pins LiteLLM `1.97.0` and FastAPI `0.136.3` as a tested pair.

### 9. LangSmith is observability, never workflow authority

Tracing requires explicit enablement and credentials. Exported payloads contain
allowlisted hashes, sizes, identifiers, and summaries rather than service tokens,
provider keys, full manifests, hidden QA content, or restricted artifacts. Polling
and lease-renewal loops do not create spans. SDK entry, completion, quota, auth,
timeout, and export failures are swallowed after local reporting.

Consequence: a LangSmith outage cannot change a task or workflow result. Hosted
evaluators remain explicit CI/release gates and do not approve production output.

### 10. Compatibility is retained during the split

The existing combined application remains available while Docker defaults to the
independent control-plane and supervisor services. This permits incremental client
migration and gives integration tests a compatibility reference.

## Problems Found And Resolved

| Problem | Cause | Resolution |
| --- | --- | --- |
| Linux Docker build could not find an agent Dockerfile | Compose used `Dockerfile.Agent`, but the file is `Dockerfile.agent` | Corrected the case-sensitive path |
| Port 8000 was unavailable | An orphaned legacy combined container still owned the port | Removed that project container and used `--remove-orphans` |
| Control-plane startup required LangGraph accidentally | `core.database` eagerly imported checkpoint modules | Made optional checkpoint imports lazy/guarded |
| LiteLLM crashed importing FastAPI internals | LiteLLM `1.97.0` resolved an incompatible newer FastAPI | Added a tested FastAPI `0.136.3` pin |
| One approval created repeated supervisor commands | Idempotency was derived from the latest action event | Keyed approvals by approval ID and decision |
| Approval workflows failed output validation | Validator accepted only `COMPLETED` worker output | Accepted durable `AWAITING_APPROVAL` output with a thread ID |
| `python scripts/test.py` could not find quality tools | System Python has no repository dev dependencies | Use `.venv/Scripts/python.exe scripts/test.py`; do not mutate global Python |

## Validation Evidence

The following passed after deleting the Compose project's containers, local
images, network, and named Postgres volume, then rebuilding from a fresh volume:

- Ruff: all checks passed.
- Mypy strict gate: no issues in 92 source files.
- Pytest: 103 passed; one third-party deprecation warning.
- Compose: all seven long-running services started; health checks passed.
- Migration: DDL files `000` through `007` applied to the empty database.
- Direct API: LangGraph and ADK worker invocations completed.
- Workflow: multi-step smoke workflow reached `COMPLETED`.
- Persistence: the expected supervisor, assignment, output, validation, and
  workflow-completed events were present in Postgres.
- Logs: zero unexpected error matches and zero known transient provider matches.
- LangSmith: runtime check skipped because credentials were not configured; unit
  tests cover disabled tracing and exporter failure isolation.

Generated databases, logs, and sanity reports are deliberately ignored by Git.
They remain local diagnostic evidence and are not source artifacts.

## Remaining Plan Work

The following `plan.md` capabilities are deliberately still open:

- A true concurrent DAG scheduler with fan-out, join barriers, and out-of-order
  branch completion. Current dependency metadata is ready for this, but execution
  is serial.
- Structured `planning.input_requested` and `planning.input_provided` forms for
  long-task clarification and checkpointed planning resume.
- Model-based evidence and hallucination review, semantic supervisor rejection,
  bounded replanning, sibling-result reuse, and final answer compilation.
- Fully normalized request, plan, step, attempt, manifest, artifact, validation,
  approval, and dead-letter tables described in the target DDL.
- Fine-grained artifact authorization and database-enforced hidden-input access.
- Workflow Playground graph, checkpoint, input-form, approval, retry, and final
  result UI described in `plan.md`.
- Hosted LangSmith trace/evaluator validation with real credentials in explicit CI.
- Full T01-T57 acceptance matrix, load tests, crash/recovery tests, and production
  security review.

## Next Implementation Order

1. Normalize the plan/step/attempt/input-manifest persistence model and migrations.
2. Add readiness reconciliation and a concurrent dependency-aware scheduler.
3. Add planning input request/provide events and checkpointed resume APIs.
4. Add supervisor semantic validation, evidence requests, bounded replan, and final
   compilation.
5. Complete Workflow Playground views against only public control-plane APIs.
6. Add crash recovery, parallel isolation, authorization, and hosted evaluation
   gates before production rollout.
