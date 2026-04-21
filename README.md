# agentmesh
Agentic job automation system using MCP and A2A communication


You are building a hybrid multi-agent system called "agentmesh".

Load all steering files from `.kiro/steering/`.

System Design:

The system must support BOTH:
1. Orchestration (central workflow control)
2. A2A (agent-to-agent event-driven collaboration)

Core Principles:

- MCP is the shared memory and event log (single source of truth)
- Every action MUST be recorded as an event
- All components use:
  - conversation_id
  - workflow_id

Architecture Rules:

1. MCP:
   - Stores all events and state
   - Does NOT make decisions
   - Provides:
     - append_event()
     - get_events()
     - get_state()

2. Orchestrator:
   - Reads MCP state
   - Decides workflow steps
   - Assigns tasks to agents
   - Logs all decisions

3. Agents:
   - Execute tasks independently
   - Can react to events (A2A)
   - Must log all outputs

A2A Communication Model:

- Agents do NOT call each other directly
- Agents communicate by:
  - emitting events
  - reacting to relevant events

Event Model:

Each event must include:
- conversation_id
- workflow_id
- event_type
- source_agent
- target_agent (optional)
- payload
- timestamp

Event Types:

- System events (orchestrator-driven)
  e.g., TASK_ASSIGNED, WORKFLOW_STARTED

- Agent events (A2A)
  e.g., JOB_DETECTED, EMAIL_FOUND

Storage Design:

- events table (append-only)
- current_state table (latest projection)

Constraints:

- No tight coupling
- No hidden state outside MCP
- All workflows must be reconstructable from events

Output Requirements:

- Clean modular structure under mcp/memory-server/src
- API layer (FastAPI)
- Service layer (event + state logic)
- Storage layer (DB)

Focus:

Build a scalable hybrid system where:
- Orchestration handles structured workflows
- A2A enables flexible collaboration
- MCP provides full observability and replayability