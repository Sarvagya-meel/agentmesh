# Replay, Checkpoints, Recovery, and Retry

This guide explains how AgentMesh reconstructs workflow state, stores resumable
LangGraph execution state, retries failed work, and starts new executions from
historical state.

## Runtime Records

AgentMesh uses three related but distinct forms of persistence.

| Record | Owner | Purpose |
|---|---|---|
| `Event` | Control plane | Immutable history of workflow activity |
| LangGraph checkpoint | Supervisor | Resumable graph state for one workflow thread |
| `AssignmentClaim` | Control plane | Mutable lease, attempt, retry, and dead-letter state |

Events explain what happened. Checkpoints describe where graph execution can
continue. Claims control which runtime may execute an assignment and when it may
retry.

## Event Data Model

`Event` is the canonical append-only workflow record:

```json
{
  "event_id": "event-7",
  "conversation_id": "conversation-1",
  "workflow_id": "workflow-1",
  "sequence_number": 7,
  "event_type": "TASK_ASSIGNED",
  "source_agent": "orchestrator-supervisor-agent",
  "routing_mode": "DIRECTED",
  "target_agent": "langgraph-copilot",
  "payload": {
    "task": {
      "task_id": "task-1",
      "agent_id": "langgraph-copilot",
      "description": "Draft a response"
    }
  },
  "causation_id": "event-6",
  "metadata": {}
}
```

PostgreSQL stores these records in `agentmesh_events`. The pair
`(workflow_id, sequence_number)` is unique, giving each workflow a deterministic
event order.

## Event Replay

Event replay rebuilds the current workflow projection without executing agents.
`EventService.replay(workflow_id)` loads the ordered history and
`StateService.project(events)` folds each event into a `WorkflowState`.

```text
WORKFLOW_STARTED        -> RUNNING
PLAN_APPROVAL_REQUESTED -> AWAITING_PLAN_APPROVAL
TASK_ASSIGNED           -> WAITING_FOR_AGENT
TASK_COMPLETED          -> RUNNING and append task result
TASK_FAILED             -> FAILED
WORKFLOW_COMPLETED      -> COMPLETED
```

Given the same ordered events, projection should always produce the same status,
current task, assigned agents, pending input, results, and workflow metadata.

Event replay does not call LangGraph, workers, model providers, or external tools.

## LangGraph Checkpointer

The supervisor compiles its graph with a checkpointer. AgentMesh uses the
workflow ID as LangGraph's thread ID:

```json
{
  "configurable": {
    "thread_id": "workflow-1",
    "checkpoint_id": "checkpoint-12"
  }
}
```

A checkpoint conceptually contains:

```json
{
  "thread_id": "workflow-1",
  "checkpoint_id": "checkpoint-12",
  "values": {
    "workflow_id": "workflow-1",
    "goal": "Prepare an application",
    "task_index": 1,
    "current_task": {"task_id": "task-2"},
    "task_results": [
      {"task_id": "task-1", "result": {"answer": "done"}}
    ]
  },
  "next": ["wait_for_task_result"],
  "metadata": {
    "step": 14,
    "source": "loop"
  }
}
```

For Docker execution, `AsyncPostgresSaver` stores native LangGraph checkpoints in
PostgreSQL. Local tests may use `MemorySaver`.

Checkpoints are written around graph node transitions and interrupts. A workflow
waiting for plan approval or a worker result therefore has a durable continuation
point.

## Checkpoint History

`GET /workflows/{workflow_id}/checkpoints` returns the snapshots available for a
workflow thread. Each item exposes:

```json
{
  "checkpoint_id": "checkpoint-12",
  "created_at": "2026-09-02T10:00:00Z",
  "next": ["wait_for_task_result"],
  "metadata": {}
}
```

An empty `next` list means the checkpoint is terminal. A checkpoint with one or
more next nodes can potentially be recovered as a new executable workflow.

## Read-Only Checkpoint Replay

The replay API inspects historical graph state:

```http
POST /workflows/workflow-1/replay
Content-Type: application/json

{"checkpoint_id":"checkpoint-12"}
```

Example response:

```json
{
  "mode": "read_only_replay",
  "workflow_id": "workflow-1",
  "checkpoint_id": "checkpoint-12",
  "next": ["wait_for_task_result"],
  "state": {
    "task_index": 1,
    "current_task": {"task_id": "task-2"}
  },
  "metadata": {}
}
```

Replay calls `graph.aget_state()` only. It does not invoke the graph, append new
events, dispatch workers, or repeat external side effects. The source workflow is
unchanged.

## Diagnostic Fork

A diagnostic fork copies checkpoint values into a new LangGraph thread and may
apply explicitly supplied state updates:

```text
workflow-1/checkpoint-12
          |
          +-> diagnostic workflow-2
              feedback = "Diagnostic fork"
```

The fork uses `graph.aupdate_state()` but does not invoke the graph. It is useful
for inspection and controlled experiments without modifying the source thread.

## Executable Checkpoint Recovery

Recovery continues historical state in a new immutable workflow history:

```text
workflow-1/checkpoint-12
          |
          +-> workflow-2
              WORKFLOW_STARTED
              WORKFLOW_RECOVERY_STARTED
              PLAN_CREATED
              prior TASK_COMPLETED records
              continue from checkpoint.next
```

Recovery performs these steps:

1. Load the requested checkpoint, or locate the latest recoverable checkpoint.
2. Reject a missing checkpoint or one with an empty `next` list.
3. Generate a new workflow ID.
4. Copy checkpoint values and replace `values.workflow_id` with the new ID.
5. Append recovery history to the new workflow event stream.
6. Copy the plan and previously completed task results into the new history.
7. Store the copied state under the new LangGraph thread ID.
8. Call `graph.ainvoke(None)` to continue from the checkpoint's next node.

The source event history and source checkpoint remain unchanged. Previously
completed task results are represented in the new history so state projection is
consistent with the recovered graph state.

## Workflow and Task Reruns

Rerun is different from checkpoint recovery.

### Workflow Rerun

The source workflow receives `WORKFLOW_RERUN_REQUESTED`. A fresh workflow ID is
created using the original goal and previously selected agent IDs. Planning starts
again from the beginning.

```text
workflow-1 -> WORKFLOW_RERUN_REQUESTED(new_workflow_id=workflow-3)
workflow-3 -> WORKFLOW_STARTED(rerun_of_workflow_id=workflow-1)
```

### Task Rerun

The source workflow receives `TASK_RERUN_REQUESTED`. A fresh workflow executes
the selected task description with the original task agent preferred.

```text
workflow-1 -> TASK_RERUN_REQUESTED(task_id=task-1, new_workflow_id=workflow-4)
workflow-4 -> WORKFLOW_STARTED(
                rerun_of_workflow_id=workflow-1,
                rerun_of_task_id=task-1
              )
```

Neither rerun overwrites the original workflow.

## Retry Data Model

Retries reuse the original assignment event and update its `AssignmentClaim`:

```json
{
  "event_id": "event-7",
  "agent_id": "langgraph-copilot",
  "worker_id": "worker-A",
  "claim_token": "claim-token-1",
  "attempt_number": 1,
  "max_attempts": 3,
  "lease_expires_at": "2026-09-02T10:00:30Z",
  "next_attempt_at": "2026-09-02T10:00:12Z",
  "last_error_code": "TimeoutError",
  "last_error_message": "Provider timed out",
  "retryable": true,
  "dead_lettered_at": null,
  "idempotency_key": "stable-assignment-key"
}
```

PostgreSQL stores this mutable state in `agentmesh_event_claims`.

### Retry Sequence

```text
TASK_ASSIGNED event-7
       |
       +-> claim attempt 1
             |
             +-> transient failure
                   next_attempt_at = now + backoff
       |
       +-> claim attempt 2 after next_attempt_at
             |
             +-> TASK_COMPLETED
```

The assignment `event_id` and `idempotency_key` remain stable. Every attempt gets
a new claim token. This prevents two workers from owning the same attempt while
still identifying all retries as one logical assignment.

Worker retry delay combines exponential backoff, jitter, and any provider
`Retry-After` value. The delay is capped at 60 seconds. Timeout, connection, HTTP
429, and server failures are retryable. Validation and malformed-payload failures
are terminal.

After the maximum attempt count is reached:

```json
{
  "attempt_number": 3,
  "retryable": false,
  "next_attempt_at": null,
  "dead_lettered_at": "2026-09-02T10:01:00Z"
}
```

## Retry and Checkpoint Interaction

When a worker assignment is retried, the supervisor graph remains interrupted at
`wait_for_task_result`. Retry does not rewind or copy the graph checkpoint.

```text
Supervisor checkpoint: wait_for_task_result
Worker attempt 1: timeout
Control plane: schedules retry
Worker attempt 2: completes
Control plane: submits terminal result
Supervisor: resumes the same workflow thread
```

Only the successful result or terminal failure resumes the supervisor graph. This
prevents transient attempts from advancing workflow state.

Supervisor actions have their own claims and retry budget. A transient supervisor
failure appends `SUPERVISOR_ACTION_RETRY_SCHEDULED`, and the same durable action is
available again after its retry time.

## Current Limitations

- Worker retry scheduling is durable in `agentmesh_event_claims`, but it does not
  append an immutable `TASK_RETRY_SCHEDULED` event.
- Event metadata contains an event cursor checkpoint such as `event:{event_id}`,
  but there is no explicit AgentMesh-owned table mapping every workflow event to
  the corresponding native LangGraph checkpoint ID.
- Checkpoint recovery copies completed task results into a new history, but any
  external side effects performed before the checkpoint must still be idempotent.
- A single workflow currently dispatches tasks by `task_index`; dependency-ready
  sibling tasks are not yet fanned out in parallel.

## Steps to Implement Next

1. Add `TASK_RETRY_SCHEDULED` and `TASK_DEAD_LETTERED` event types.
   Append them transactionally when claim retry state changes, including attempt,
   error code, next-at time, and assignment causation ID.
2. Add an explicit workflow-event/checkpoint mapping table.
   Store `workflow_id`, event ID, event sequence, LangGraph thread ID, checkpoint
   ID, checkpoint namespace, and checkpoint operation.
3. Make event append, claim transition, and checkpoint mapping atomic where the
   service boundary permits it. Add reconciliation for a checkpoint written just
   before an event append failure, and vice versa.
4. Add recovery side-effect guards.
   Require workers and tools to consume the stable assignment idempotency key and
   persist external operation identifiers before recovery can repeat a step.
5. Expose retry attempts in workflow activity.
   Project retrying and dead-letter states from immutable retry events so
   Streamlit can display attempt number, next retry time, and failure reason.
6. Implement dependency-ready parallel dispatch.
   Replace the single `task_index` cursor with ready, running, blocked, completed,
   and failed task sets, then checkpoint after each fan-out and `all_required`
   join transition.
7. Expand automated validation.
   Cover worker restart during retry delay, lease expiry, duplicate terminal
   results, read-only replay side-effect absence, source-history immutability,
   recovery from every non-terminal node, checkpoint/event reconciliation, and
   parallel completion in different orders.
8. Add persistent PostgreSQL UAT cases for the new retry events, checkpoint
   mappings, recovery idempotency, and parallel joins before enabling them in the
   Streamlit operations view.
