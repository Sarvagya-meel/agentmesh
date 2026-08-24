# Agent Runtime, API, Worker, and Registry Guide

This document explains the current AgentMesh V1 runtime. It focuses on how the
LangGraph agent is started, how API and worker profiles deliver work to the same
execution contract, how the registry tracks logical agents and running instances,
and how PostgreSQL coordinates durable workflows and assignment claims.

## Core Principle

API and worker modes are inbound interfaces around the same agent execution path:

```text
FastAPI /invoke ---------+
                         +--> AgentExecutor --> BaseAgent.arun_task() --> LangGraph
Assignment worker -------+
```

Communication types used in the diagrams:

- **In-process Python call:** communication between objects in one process.
- **Internal HTTP:** communication between containers on the Docker network.
- **SQL:** durable state and coordination through PostgreSQL.
- **External HTTPS:** communication with an LLM provider.

## API Profile

The API profile exposes direct invocation and conversation endpoints. It registers
and sends presence heartbeats, but it does not poll for queued assignments.

```mermaid
flowchart LR
    subgraph EXT["External / Host"]
        USER["User"]
        BROWSER["Browser"]
    end

    subgraph DOCKER["Docker Network"]
        UI["Streamlit UI<br/>port 8501"]
        CONTROL["Control Plane<br/>port 8000"]

        subgraph API["LangGraph API Process<br/>AGENT_RUNTIME_ROLE=api"]
            FASTAPI["FastAPI Runtime"]
            ROUTES["/health<br/>/ready<br/>/agent-card<br/>/invoke<br/>/conversations/*"]
            EXECUTOR["One AgentExecutor"]
            AGENT["One ConversationAgent"]
            GRAPH["Compiled LangGraph"]
        end

        POSTGRES[("PostgreSQL")]
    end

    MODEL["External LLM Provider"]

    USER --> BROWSER
    BROWSER -->|"HTTP localhost:8501"| UI
    UI -->|"Internal HTTP"| CONTROL
    UI -->|"Internal HTTP /invoke"| ROUTES
    FASTAPI --> ROUTES
    ROUTES -->|"In-process"| EXECUTOR
    EXECUTOR -->|"arun_task()"| AGENT
    AGENT -->|"graph.ainvoke()"| GRAPH
    GRAPH -->|"SQL checkpoints and Store"| POSTGRES
    GRAPH -->|"External HTTPS"| MODEL
```

In the split profile, the API service does not currently publish port `8101` to
the host. Streamlit reaches it through the Docker network by using the endpoint
published in the Agent Card. Combined mode publishes `8101` for convenient direct
local testing.

### Direct Invocation

```mermaid
sequenceDiagram
    participant UI as Streamlit
    participant API as FastAPI /invoke
    participant EX as AgentExecutor
    participant LG as ConversationAgent
    participant G as LangGraph
    participant DB as PostgreSQL
    participant LLM as Model Provider

    UI->>API: POST /invoke with message and thread_id
    API->>API: Validate InvokeRequest
    API->>EX: execute(payload, source=direct)
    EX->>EX: Acquire concurrency permit
    EX->>EX: Lock the same thread_id
    EX->>LG: arun_task(payload, context)
    LG->>G: graph.ainvoke(state, config)
    G->>DB: Load checkpoint and message history
    G->>LLM: Generate response
    LLM-->>G: Model result
    G->>DB: Save graph checkpoint
    G-->>LG: Final or interrupted state
    LG-->>EX: Structured result
    EX-->>API: Release lock and permit
    API-->>UI: HTTP response
```

The registry is used to discover the direct endpoint and verify readiness. It is
not called for every graph node or model request.

## API Profile Registration

The runtime currently uses `AssignmentWorker` for both presence and assignment
consumption. In API mode it performs only the presence responsibilities.

```mermaid
sequenceDiagram
    participant API as LangGraph API Process
    participant P as Runtime Presence Component
    participant RA as Registry FastAPI
    participant RS as RegistryService
    participant AC as agentmesh_agents
    participant RR as agentmesh_resources

    API->>P: start(runtime_role=api)
    P->>RA: PUT /registry/agents/langgraph-copilot
    RA->>RS: upsert_agent(AgentCard)
    RS->>AC: INSERT ON CONFLICT UPDATE
    AC-->>RS: Stored Agent Card
    RS-->>P: Registered Agent Card
    P->>RR: UPSERT unique API runtime resource

    loop Every 60 seconds
        P->>RA: POST /registry/agents/{id}/heartbeat
        RA->>RS: heartbeat(agent_id, telemetry)
        RS->>AC: Update logical card last_seen
        P->>RR: Update runtime last_seen and telemetry
    end

    Note over P: consume_assignments=false
```

API mode provides:

- registration and heartbeat
- health and readiness
- Agent Card discovery
- direct invocation and conversation endpoints
- no assignment polling

## Worker Profile

Worker mode registers itself, polls the control plane for directed assignments,
claims work through PostgreSQL leases, executes the same agent contract, and
submits a claim-authenticated result. It deliberately has no `/invoke` route.

```mermaid
flowchart LR
    subgraph CONTROL["Control-Plane Process"]
        ORCHESTRATOR["Orchestrator Supervisor"]
        WORKER_API["Worker FastAPI Routes"]
        WORKER_SERVICE["WorkerService"]
        REGISTRY["RegistryService"]
    end

    subgraph WORKER["LangGraph Worker Process<br/>AGENT_RUNTIME_ROLE=worker"]
        LOOP["AssignmentWorker<br/>async polling loop"]
        CLIENT["AsyncControlPlaneClient"]
        EXECUTOR["One AgentExecutor"]
        AGENT["One ConversationAgent"]
        GRAPH["Compiled LangGraph"]
        RENEW["Lease Renewal Task"]
    end

    EVENTS[("agentmesh_events")]
    CLAIMS[("agentmesh_event_claims")]
    RESOURCES[("agentmesh_resources")]
    CHECKPOINTS[("LangGraph checkpoints")]
    MODEL["External LLM Provider"]

    ORCHESTRATOR -->|"SQL append TASK_ASSIGNED"| EVENTS
    LOOP --> CLIENT
    CLIENT -->|"HTTP GET assignments"| WORKER_API
    WORKER_API --> WORKER_SERVICE
    WORKER_SERVICE -->|"SQL find pending tasks"| EVENTS
    CLIENT -->|"HTTP POST claim"| WORKER_API
    WORKER_SERVICE -->|"SQL transaction and row lock"| CLAIMS
    LOOP -->|"Claimed task"| EXECUTOR
    EXECUTOR -->|"arun_task()"| AGENT
    AGENT -->|"graph.ainvoke()"| GRAPH
    GRAPH --> CHECKPOINTS
    GRAPH --> MODEL
    RENEW -->|"HTTP renew"| WORKER_API
    WORKER_SERVICE -->|"SQL extend lease"| CLAIMS
    LOOP -->|"HTTP submit result"| WORKER_API
    WORKER_SERVICE -->|"SQL validate claim"| CLAIMS
    WORKER_SERVICE -->|"Resume workflow"| ORCHESTRATOR
    LOOP -->|"SQL presence telemetry"| RESOURCES
```

## Polling Loop

Polling means that the worker asks the control plane for available work at a
configured interval. It is different from the executor's concurrency pool limit.

```mermaid
flowchart TD
    START["Worker process starts"] --> REGISTER["Register Agent Card"]
    REGISTER --> READY["Set runtime READY"]
    READY --> POLL["GET pending assignments"]
    POLL --> CAPACITY{"Execution capacity available?"}
    CAPACITY -->|"No"| WAIT["Wait poll interval"]
    CAPACITY -->|"Yes"| FOUND{"Assignment found?"}
    FOUND -->|"No"| WAIT
    FOUND -->|"Yes"| CLAIM["POST claim request"]
    CLAIM --> WON{"Claim granted?"}
    WON -->|"409 another worker won"| POLL
    WON -->|"Yes"| TASK["Create async execution task"]
    TASK --> RENEW["Start lease renewal"]
    TASK --> EXECUTE["AgentExecutor.execute()"]
    EXECUTE --> RESULT{"Execution result"}
    RESULT -->|"Completed"| COMPLETE["Submit COMPLETED"]
    RESULT -->|"Approval interrupt"| APPROVAL["Submit AWAITING_APPROVAL"]
    RESULT -->|"Retryable error"| RETRY["Submit RETRY"]
    RESULT -->|"Permanent error"| FAILED["Submit FAILED"]
    COMPLETE --> STOP["Stop lease renewal"]
    APPROVAL --> STOP
    RETRY --> STOP
    FAILED --> STOP
    STOP --> POLL
    WAIT --> POLL
```

With `POLL_INTERVAL_SECONDS=2`, an idle worker waits approximately two seconds
before asking again. It does not claim additional work after reaching its process
concurrency limit.

## Assignment Claim

Finding an assignment does not grant ownership. The worker must claim it:

```text
Worker Python code
    --> HTTP POST /workers/{agent_id}/assignments/{event_id}/claim
    --> FastAPI worker route
    --> WorkerService.claim_assignment()
    --> PostgresClaimRepository.try_claim()
    --> SQL transaction in agentmesh_event_claims
```

PostgreSQL locks the claim row with `SELECT ... FOR UPDATE`. The claim is granted
only when the assignment is not completed, dead-lettered, waiting for a scheduled
retry, or protected by an unexpired lease.

The stored claim includes:

- assignment event ID
- agent ID and worker-process ID
- unique claim token
- claim and lease timestamps
- attempt and maximum-attempt counts
- idempotency key

If two worker replicas race for the same assignment, PostgreSQL grants one claim.
The other receives HTTP `409 Conflict` and continues polling.

## Workflow Execution

```mermaid
sequenceDiagram
    participant U as User / Streamlit
    participant O as Orchestrator
    participant E as agentmesh_events
    participant W as Worker
    participant C as agentmesh_event_claims
    participant A as LangGraph Agent
    participant DB as Checkpoint DB

    U->>O: Start workflow with goal
    O->>E: WORKFLOW_STARTED and PLAN_CREATED
    O-->>U: AWAITING_PLAN_APPROVAL
    U->>O: Approve plan
    O->>E: PLAN_APPROVED and TASK_ASSIGNED
    O->>DB: Interrupt waiting for agent result

    loop Worker polling
        W->>E: Request pending assignments
    end

    E-->>W: Directed TASK_ASSIGNED
    W->>C: Atomically claim assignment
    C-->>W: claim_token and lease

    par Agent execution
        W->>A: arun_task()
        A->>DB: Load and save checkpoints
    and Lease protection
        W->>C: Periodically renew lease
    end

    A-->>W: COMPLETED or AWAITING_APPROVAL
    W->>O: Submit result with claim token
    O->>C: Validate ownership and active lease
    O->>DB: Command(resume=result)

    alt Agent completed
        O->>E: TASK_COMPLETED
        O->>E: Next TASK_ASSIGNED or WORKFLOW_COMPLETED
    else Agent requests approval
        O->>E: AGENT_OUTPUT_PROPOSED
        O->>E: AGENT_APPROVAL_REQUESTED
        O-->>U: AWAITING_AGENT_APPROVAL
    end
```

## Registry Model

The registry separates stable identity from process presence:

```mermaid
flowchart TD
    CARD["Logical Agent Card<br/>agentmesh_agents"]
    API1["API runtime instance<br/>agentmesh_resources"]
    WORKER1["Worker runtime instance 1<br/>agentmesh_resources"]
    WORKER2["Worker runtime instance 2<br/>agentmesh_resources"]
    AGG["RegistryService availability aggregation"]
    RESULT["Aggregated Agent Card<br/>direct_ready<br/>assignment_ready<br/>ready_runtime_count"]

    CARD --> AGG
    API1 --> AGG
    WORKER1 --> AGG
    WORKER2 --> AGG
    AGG --> RESULT
```

`agentmesh_agents` contains one row per logical agent. `agentmesh_resources`
contains one row per running process instance. The registry computes:

- `direct_ready`: a ready `api` or `combined` instance exists
- `assignment_ready`: a ready `worker` or `combined` instance exists
- `direct_endpoint`: the most recently seen direct-capable endpoint
- `ready_runtime_count`: number of fresh, ready runtime instances

Runtime instances older than the stale threshold are marked `stale`. Normal
heartbeats update presence without creating an audit event; lifecycle transitions
such as registration, degradation, recovery, draining, and shutdown are audited.

## Infrastructure Communication

```mermaid
flowchart TB
    EXTERNAL["Browser / External User"]

    subgraph NETWORK["Docker Network"]
        UI["Streamlit"]
        CONTROL["Control Plane"]
        API["Agent API Process"]
        WORKER["Agent Worker Process"]
        POSTGRES["PostgreSQL"]
    end

    MODEL["External LLM Provider"]

    EXTERNAL -->|"Published HTTP :8501"| UI
    EXTERNAL -->|"Published HTTP :8000"| CONTROL
    UI -->|"Internal HTTP"| CONTROL
    UI -->|"Internal HTTP /invoke"| API
    API -->|"Internal HTTP registration and heartbeat"| CONTROL
    WORKER -->|"Internal HTTP registration and heartbeat"| CONTROL
    WORKER -->|"Internal HTTP poll, claim, renew, result"| CONTROL
    CONTROL -->|"SQL"| POSTGRES
    API -->|"SQL checkpoints, memory, presence"| POSTGRES
    WORKER -->|"SQL checkpoints, memory, presence"| POSTGRES
    API -->|"External HTTPS"| MODEL
    WORKER -->|"External HTTPS"| MODEL
```

## Responsibility Boundaries

### Registry Service

- stores and discovers Agent Cards
- tracks and aggregates runtime-instance availability
- finds assignment-ready agents by capability
- marks stale runtime processes
- does not execute agents or claim tasks

### Worker Service

- lists pending directed assignments
- grants and renews claim leases
- validates claim-authenticated results
- schedules retries and dead-letters exhausted assignments
- resumes the orchestrator with completed worker results

### Agent Executor

- provides process-level concurrency limits
- serializes executions sharing a thread ID
- tracks active executions
- drains safely during shutdown
- invokes `BaseAgent.arun_task(payload, context)`

### LangGraph Agent

- owns reasoning and graph state
- reads and writes durable checkpoints
- communicates with the model provider
- returns structured completed, rejected, or interrupted results
- does not know whether work arrived through API or worker polling

## V2 Direction

V1 uses `AGENT_RUNTIME_ROLE=combined|api|worker`. The future composable-interface
proposal is documented in [FUTURE_PROPOSALS.md](FUTURE_PROPOSALS.md). It replaces
compound roles with settings such as `AGENT_INTERFACES=api,worker,mcp` while keeping
the shared executor and concrete agent unchanged.
