# AgentMesh Future Proposals

## V2: Composable Runtime Interfaces

### Proposal

Replace the single mutually exclusive `AGENT_RUNTIME_ROLE` setting with a list of
independently enabled runtime interfaces:

```dotenv
AGENT_INTERFACES=api,worker
```

Additional adapters can then be enabled without creating new compound role names:

```dotenv
AGENT_INTERFACES=api,worker,mcp
```

Each interface remains an inbound adapter around the shared execution boundary:

```text
FastAPI adapter ---------+
Assignment worker -------+--> AgentExecutor --> BaseAgent.arun_task()
MCP server adapter ------+
AgentCore adapter -------+
A2A adapter -------------+
```

### Why V2

The V1 roles (`combined`, `api`, and `worker`) keep local deployment simple and make
split scaling explicit. They become awkward as more interfaces are added because each
combination would otherwise require another role name. A composable interface list
keeps transport selection separate from agent reasoning and deployment topology.

### Boundaries

- Each process still creates exactly one agent and one `AgentExecutor`.
- Every inbound adapter calls the same `BaseAgent.arun_task(payload, context)` contract.
- Adapters own protocol validation and translate requests into framework-neutral payloads.
- The agent does not import FastAPI, worker polling, Docker, MCP transport, AgentCore, or A2A.
- Exposing an agent through MCP is an inbound runtime adapter.
- Letting a LangGraph agent consume MCP tools is a separate graph/tool capability.
- Presence metadata should report enabled interfaces rather than one compound role.
- Readiness remains interface-specific: API readiness, assignment readiness, and MCP readiness.

### Migration

1. Add an `AgentInterface` enum and parse `AGENT_INTERFACES`.
2. Map legacy roles for backward compatibility: `combined` to `api,worker`, `api` to
   `api`, and `worker` to `worker`.
3. Extract API route registration and assignment consumption into interface adapters.
4. Keep `AgentExecutor` and concrete agents unchanged.
5. Add the MCP server adapter only after its authentication, schemas, and capability
   advertisement are defined.
6. Remove `AGENT_RUNTIME_ROLE` after one documented compatibility period.

### Alternatives

- Keep adding roles such as `api-worker-mcp`. This is initially simple but creates a
  growing matrix of role names and tests.
- Run every adapter in a separate process. This gives maximum isolation and scaling but
  creates an agent instance per process and is heavier for local development.
- Put protocol logic inside each agent. This reduces adapter code but couples reasoning
  to deployment technology and makes AgentCore or A2A migration harder.

### Status

Future V2 proposal. V1 continues to use `AGENT_RUNTIME_ROLE=combined|api|worker`.
