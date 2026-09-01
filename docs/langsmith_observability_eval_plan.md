# LangSmith Observability And Evaluation Plan

## Goal

Make LangSmith the shared observability and evaluation layer for AgentMesh workflows, agents, assignments, persistence, and audit trails without making local development dependent on hosted credentials.

## Trace Shape

Use one trace per workflow execution. The root run should represent the workflow and include:

- `workflow_id`
- `conversation_id`
- `goal`
- `rerun_of_workflow_id`
- `rerun_of_task_id`
- selected planner provider/model
- final workflow status

Child runs should represent:

- plan creation
- plan approval request and decision
- task proposal
- task dispatch
- assignment claim and lease renewals
- agent execution
- agent output approval request and decision
- task completion/failure
- PostgreSQL checkpoint save/load
- event append/replay
- resource/audit writes

## Metadata Contract

Every traceable unit should include the smallest stable IDs needed to join LangSmith traces back to PostgreSQL:

- `workflow_id`
- `conversation_id`
- `task_id`
- `assignment_event_id`
- `agent_id`
- `runtime_instance_id`
- `worker_id`
- `claim_token_present`, never the token itself
- `checkpoint_thread_id`
- `checkpoint_namespace`
- `event_type`
- `event_id`
- `causation_id`
- `sequence_number`

Secrets and raw claim tokens must never be sent to LangSmith metadata.

## Evaluation Datasets

Create a LangSmith dataset named `AgentMesh Sanity Eval` with examples generated from the executable sanity catalog. Initial dimensions:

- direct LangGraph invocation
- direct Google ADK invocation
- multi-agent workflow completion
- approval-gate event coverage
- routing choice correctness
- final answer faithfulness to prior task output
- audit trail completeness
- LangSmith trace visibility

## Evaluators

Starter evaluators live in `scripts/langsmith_eval.py`:

- `workflow_consistency`: expected agents are planned and the workflow completes
- `approval_gate_events`: required approval events exist
- `routing_choice`: assigned agents match expected framework coverage
- `final_answer_faithfulness`: final answer preserves key terms or output overlap from prior task results

Next evaluator upgrades:

- LLM-as-judge faithfulness using a low-temperature evaluator model
- deterministic event-order evaluator for audit trails
- persistence evaluator that compares LangGraph checkpoint IDs with workflow/event state
- latency evaluator for startup/readiness and assignment turnaround
- non-functional evaluator for runtime logs and retry behavior

## CI Modes

Local default:

- Run tests and sanity checks.
- Skip LangSmith hosted checks when `LANGSMITH_API_KEY` is missing.

Explicit CI eval:

- Set `AGENTMESH_SANITY_MODE=ci`.
- Set `AGENTMESH_REQUIRE_LANGSMITH=1`.
- Fail when LangSmith config is missing, authentication fails, trace lookup fails, or required evaluators score below threshold.

## Implementation Phases

1. Keep Compose and local settings exporting both `LANGSMITH_*` and `LANGCHAIN_*` compatibility variables.
2. Wrap control-plane workflow entry points and supervisor planning actions in trace spans with workflow-level metadata.
3. Add spans around event append/query, supervisor claim/result, worker claim/renew/result, registry aggregation, and checkpoint mapping persistence.
4. Generate LangSmith dataset examples from `agentmesh.testing.sanity_catalog`.
5. Promote the sanity runner to CI with explicit secret-gated LangSmith failure behavior.
6. Add dashboard/report views that join LangSmith run IDs with PostgreSQL `agentmesh_events`, claims, resources, and audit rows.
