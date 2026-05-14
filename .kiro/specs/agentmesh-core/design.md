# Design Document: AgentMesh Core

## Overview

AgentMesh Core is a production-grade hybrid multi-agent system built on FastAPI. The Memory Control Plane (MCP) is the single source of truth — an append-only event log with deterministic state projection. The Orchestrator makes all workflow decisions. Agents execute tasks independently and communicate exclusively through MCP events.

The implementation lives under `mcp/memory-server/src/` with a strict API → Service → Storage layering.

---

## Project Structure

```
mcp/
└── memory-server/
    └── src/
        ├── api/
        │   ├── __init__.py
        │   ├── routes/
        │   │   ├── events.py
        │   │   ├── state.py
        │   │   └── workflows.py
        │   └── dependencies.py
        ├── services/
        │   ├── event_service.py
        │   ├── state_service.py
        │   └── orchestrator_service.py
        ├── storage/
        │   ├── models.py
        │   ├── repository.py
        │   └── migrations/
        ├── agents/
        │   ├── base.py
        │   ├── job_detector.py
        │   ├── email_finder.py
        │   └── applicator.py
        ├── core/
        │   ├── models.py
        │   ├── event_types.py
        │   └── exceptions.py
        └── main.py
```

---

## Components and Interfaces

### EventService
Validates, persists, and queries events. Enforces append-only semantics and idempotency. Raises domain exceptions for invalid or duplicate events.

### StateService
Projects `WorkflowState` from an ordered event list. Pure deterministic function. Also manages the materialized `current_state` cache via incremental updates after each append.

### OrchestratorService
Reads workflow state from MCP, makes deterministic workflow decisions, and emits task events. Never calls agents directly.

### BaseAgent
Abstract polling loop with four guards (subscription filter, processed-type check, pending-type check, causation loop detection). Dispatches events by routing mode (DIRECTED, FANOUT, CLAIMED).

### EventRepository / StateRepository / ClaimRepository
Abstract interfaces for persistence. Concrete implementations in `pg_repository.py` use SQLAlchemy async + asyncpg.

### MCPInterface (Protocol)
```python
class MCPInterface(Protocol):
    async def append_event(self, event: Event) -> Event: ...
    async def get_events(self, filters: EventFilters) -> list[Event]: ...
    async def get_state(self, workflow_id: str) -> WorkflowState: ...
    async def try_claim_event(self, event_id: UUID, agent_id: str) -> bool: ...
```

---

## Data Models

### Event
```python
@dataclass
class Event:
    conversation_id: str       # mandatory — top-level session identifier
    workflow_id: str           # mandatory — specific workflow instance (UUID v4)
    event_type: str            # must be in REGISTERED_EVENT_TYPES
    source_agent: str          # must be in REGISTERED_AGENTS or "orchestrator"
    payload: dict              # JSON-serializable
    timestamp: datetime        # UTC
    event_id: UUID             # globally unique idempotency key
    target_agent: str | None   # set for DIRECTED routing
    routing_mode: RoutingMode  # DIRECTED | FANOUT | CLAIMED
    routing_weights: dict[str, float] | None  # agent_id → weight for FANOUT
    causation_chain: list[UUID]  # ancestor event IDs, root-to-parent order
    sequence_number: int       # monotonically increasing per workflow_id
```

### WorkflowState
```python
@dataclass
class WorkflowState:
    workflow_id: str
    conversation_id: str
    status: WorkflowStatus          # PENDING | RUNNING | COMPLETED | FAILED
    current_step: str | None
    assigned_agents: list[str]
    last_event_id: UUID | None
    updated_at: datetime
    metadata: dict
    processed_event_types: list[str]  # event types already handled
    pending_event_types: list[str]    # event types expected next
```

### Task
```python
@dataclass
class Task:
    task_id: UUID
    workflow_id: str
    conversation_id: str
    agent_id: str
    task_type: str
    payload: dict
    created_at: datetime
```

### WorkflowContext
```python
@dataclass
class WorkflowContext:
    conversation_id: str
    workflow_id: str
    goal: str
    initial_payload: dict
    created_at: datetime
```

### EventFilters
```python
@dataclass
class EventFilters:
    workflow_id: str
    conversation_id: str | None = None
    event_type: str | None = None
    source_agent: str | None = None
    target_agent: str | None = None
    since: datetime | None = None
    limit: int = 100
```

### WorkflowDecision
```python
@dataclass
class WorkflowDecision:
    action: str   # ASSIGN_TASK | COMPLETE | FAIL | WAIT
    agent_id: str | None = None
    task_payload: dict = field(default_factory=dict)
    summary: str = ""
    reason: str = ""
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     API Layer                        │
│         events.py  │  state.py  │  workflows.py      │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                   Service Layer                      │
│   EventService  │  StateService  │  OrchestratorSvc  │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                   Storage Layer                      │
│       events  │  current_state  │  event_claims      │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                    Agent Layer                       │
│  BaseAgent │ JobDetectorAgent │ EmailFinderAgent      │
│                  ApplicationAgent                    │
└─────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────┐
│                    Core Layer                        │
│      models.py  │  event_types.py  │  exceptions.py  │
└─────────────────────────────────────────────────────┘
```

---

## API Endpoints

### Events

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events` | Append a new event to MCP |
| `GET` | `/events` | Query events with filters |

### State

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/state/{workflow_id}` | Get current projected state |

### Workflows

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/workflows/start` | Start a new workflow |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |

---

## Pydantic Request/Response Schemas

```python
# api/schemas.py

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from src.core.models import RoutingMode


class AppendEventRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    workflow_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    source_agent: str = Field(..., min_length=1)
    payload: dict
    target_agent: str | None = None
    routing_mode: RoutingMode = RoutingMode.DIRECTED
    routing_weights: dict[str, float] | None = None
    causation_chain: list[UUID] = Field(default_factory=list)

    @field_validator("routing_weights")
    @classmethod
    def weights_must_be_non_negative(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is not None:
            for k, w in v.items():
                if w < 0:
                    raise ValueError(f"routing_weight for {k} must be >= 0")
        return v


class EventResponse(BaseModel):
    event_id: UUID
    conversation_id: str
    workflow_id: str
    event_type: str
    source_agent: str
    payload: dict
    timestamp: datetime
    target_agent: str | None
    routing_mode: RoutingMode
    routing_weights: dict[str, float] | None
    causation_chain: list[UUID]
    sequence_number: int


class EventQueryParams(BaseModel):
    workflow_id: str
    since: datetime | None = None
    event_type: str | None = None
    source_agent: str | None = None
    target_agent: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class StartWorkflowRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1)
    workflow_id: str = Field(..., min_length=1)
    goal: str = Field(..., min_length=1)
    initial_payload: dict = Field(default_factory=dict)

    @field_validator("workflow_id")
    @classmethod
    def must_be_uuid4(cls, v: str) -> str:
        try:
            UUID(v, version=4)
        except ValueError:
            raise ValueError("workflow_id must be a valid UUID v4")
        return v


class StartWorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    event_id: UUID


class WorkflowStateResponse(BaseModel):
    workflow_id: str
    conversation_id: str
    status: str
    current_step: str | None
    assigned_agents: list[str]
    last_event_id: UUID | None
    updated_at: datetime
    processed_event_types: list[str]
    pending_event_types: list[str]
    metadata: dict
```

---

## Core Domain Models

```python
# core/models.py

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class RoutingMode(str, Enum):
    DIRECTED = "DIRECTED"
    FANOUT = "FANOUT"
    CLAIMED = "CLAIMED"


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Event:
    conversation_id: str
    workflow_id: str
    event_type: str
    source_agent: str
    payload: dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: UUID = field(default_factory=uuid4)
    target_agent: str | None = None
    routing_mode: RoutingMode = RoutingMode.DIRECTED
    routing_weights: dict[str, float] | None = None
    causation_chain: list[UUID] = field(default_factory=list)
    sequence_number: int = 0


@dataclass
class WorkflowState:
    workflow_id: str
    conversation_id: str
    status: WorkflowStatus
    current_step: str | None
    assigned_agents: list[str]
    last_event_id: UUID | None
    updated_at: datetime
    metadata: dict = field(default_factory=dict)
    processed_event_types: list[str] = field(default_factory=list)
    pending_event_types: list[str] = field(default_factory=list)


@dataclass
class Task:
    task_id: UUID
    workflow_id: str
    conversation_id: str
    agent_id: str
    task_type: str
    payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class WorkflowContext:
    conversation_id: str
    workflow_id: str
    goal: str
    initial_payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EventFilters:
    workflow_id: str
    conversation_id: str | None = None
    event_type: str | None = None
    source_agent: str | None = None
    target_agent: str | None = None
    since: datetime | None = None
    limit: int = 100


@dataclass
class WorkflowDecision:
    action: str  # ASSIGN_TASK | COMPLETE | FAIL | WAIT
    agent_id: str | None = None
    task_payload: dict = field(default_factory=dict)
    summary: str = ""
    reason: str = ""
```

---

## Event Type Registry

```python
# core/event_types.py

from enum import Enum


class EventType(str, Enum):
    # Orchestrator-driven
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_CANCELLED = "TASK_CANCELLED"

    # Agent-driven
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    JOB_DETECTED = "JOB_DETECTED"
    EMAIL_FOUND = "EMAIL_FOUND"
    APPLICATION_SENT = "APPLICATION_SENT"

    # Infrastructure
    EVENT_CLAIMED = "EVENT_CLAIMED"

REGISTERED_EVENT_TYPES: frozenset[str] = frozenset(e.value for e in EventType)
```

---

## Exception Hierarchy

```python
# core/exceptions.py

class AgentMeshError(Exception):
    """Base exception for all AgentMesh domain errors."""

class EventValidationError(AgentMeshError):
    """Raised when an event fails validation before DB write."""

class UnknownEventTypeError(EventValidationError):
    """Raised when event_type is not in the registered registry."""

class UnknownAgentError(EventValidationError):
    """Raised when source_agent or target_agent is not registered."""

class CausationLoopError(EventValidationError):
    """Raised when the causation chain contains a cycle."""

class DuplicateEventError(AgentMeshError):
    """Raised (internally) when event_id already exists — triggers idempotent return."""

class MCPUnavailableError(AgentMeshError):
    """Raised when the database/MCP is unreachable."""

class WorkflowConflictError(AgentMeshError):
    """Raised when a workflow_id already has a WORKFLOW_STARTED event."""

class WorkflowNotFoundError(AgentMeshError):
    """Raised when no events exist for the requested workflow_id."""

class ClaimConflictError(AgentMeshError):
    """Raised when an event_claim insert fails due to unique constraint."""
```

---

## SQLAlchemy ORM Tables

```python
# storage/models.py

from datetime import datetime
from uuid import UUID
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(sa.String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    source_agent: Mapped[str] = mapped_column(sa.String, nullable=False)
    target_agent: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    routing_mode: Mapped[str] = mapped_column(sa.String, nullable=False, default="DIRECTED")
    routing_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    causation_chain: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sequence_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        sa.Index("ix_events_workflow_timestamp", "workflow_id", "timestamp"),
        sa.UniqueConstraint("workflow_id", "sequence_number", name="uq_events_workflow_seq"),
    )


class CurrentStateRow(Base):
    __tablename__ = "current_state"

    workflow_id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    current_step: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    assigned_agents: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    last_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    processed_event_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    pending_event_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class EventClaimRow(Base):
    __tablename__ = "event_claims"

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("event_id", name="uq_event_claims_event_id"),
    )
```

---

## Repository Interface

```python
# storage/repository.py

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID
from src.core.models import Event, WorkflowState, EventFilters


class EventRepository(ABC):
    """Abstract repository for event persistence."""

    @abstractmethod
    async def append(self, event: Event) -> Event:
        """Append an event. Returns existing event if event_id already exists (idempotent)."""

    @abstractmethod
    async def query(self, filters: EventFilters) -> list[Event]:
        """Return events matching filters, ordered by timestamp ascending."""

    @abstractmethod
    async def get_by_id(self, event_id: UUID) -> Event | None:
        """Return a single event by its ID, or None if not found."""

    @abstractmethod
    async def get_next_sequence_number(self, workflow_id: str) -> int:
        """Return the next sequence number for a workflow (atomic)."""


class StateRepository(ABC):
    """Abstract repository for materialized state."""

    @abstractmethod
    async def get(self, workflow_id: str) -> WorkflowState | None:
        """Return the current materialized state, or None if not found."""

    @abstractmethod
    async def upsert(self, state: WorkflowState) -> None:
        """Insert or update the materialized state for a workflow."""


class ClaimRepository(ABC):
    """Abstract repository for event claims."""

    @abstractmethod
    async def try_claim(self, event_id: UUID, agent_id: str) -> bool:
        """
        Atomically insert a claim record.
        Returns True if this agent won the claim, False if already claimed.
        Implemented via INSERT ... ON CONFLICT DO NOTHING.
        """

    @abstractmethod
    async def get_claim(self, event_id: UUID) -> str | None:
        """Return the agent_id that holds the claim, or None."""
```

---

## Service Interfaces

```python
# services/event_service.py (interface)

class EventService:
    """
    Core service for event persistence and querying.
    Enforces append-only semantics, validation, and idempotency.
    """

    async def append(self, event: Event) -> Event:
        """
        Validate and persist an event.
        Idempotent: returns existing event if event_id already exists.
        Raises: EventValidationError, UnknownEventTypeError, UnknownAgentError,
                CausationLoopError, MCPUnavailableError
        """

    async def query(self, filters: EventFilters) -> list[Event]:
        """Return events matching filters. Raises: MCPUnavailableError"""

    async def replay(self, workflow_id: str) -> list[Event]:
        """Return all events for a workflow in ascending timestamp order."""


# services/state_service.py (interface)

class StateService:
    """
    Manages workflow state as a deterministic projection of the event log.
    """

    def project(self, events: list[Event]) -> WorkflowState:
        """
        Pure function. Project WorkflowState from an ordered event list.
        No I/O. Deterministic. Same input always produces same output.
        """

    async def get_current(self, workflow_id: str) -> WorkflowState:
        """
        Return the materialized state. Falls back to projection if not cached.
        Raises: WorkflowNotFoundError, MCPUnavailableError
        """

    async def update_after_append(self, event: Event) -> None:
        """Incrementally update materialized state after a new event is appended."""


# services/orchestrator_service.py (interface)

class OrchestratorService:
    """
    Evaluates workflow state and emits task events.
    Makes all structured workflow decisions. Never calls agents directly.
    """

    async def start_workflow(self, context: WorkflowContext) -> str:
        """
        Append WORKFLOW_STARTED event and return workflow_id.
        Raises: WorkflowConflictError if workflow already started.
        """

    def decide(self, state: WorkflowState) -> WorkflowDecision:
        """
        Pure deterministic decision function.
        Returns ASSIGN_TASK, COMPLETE, FAIL, or WAIT.
        No I/O. No side effects.
        """

    async def run_loop(self, workflow_id: str) -> None:
        """
        Continuously read state from MCP, decide, and emit events.
        Stops when workflow reaches COMPLETED or FAILED.
        """
```

---

## State Projection Algorithm

```python
from dataclasses import replace
from src.core.models import Event, WorkflowState, WorkflowStatus


def project_state(events: list[Event], workflow_id: str, conversation_id: str) -> WorkflowState:
    """
    Preconditions:
      - events is ordered by sequence_number ascending
      - all events share the same workflow_id

    Postconditions:
      - Returned state reflects all events applied in order
      - Function is pure — no I/O, no side effects
      - Same input always produces same output

    Loop Invariant:
      - state is a valid projection of all events processed so far
    """
    state = WorkflowState(
        workflow_id=workflow_id,
        conversation_id=conversation_id,
        status=WorkflowStatus.PENDING,
        current_step=None,
        assigned_agents=[],
        last_event_id=None,
        updated_at=events[0].timestamp if events else datetime.utcnow(),
    )

    for event in events:
        match event.event_type:
            case "WORKFLOW_STARTED":
                state = replace(state, status=WorkflowStatus.RUNNING, updated_at=event.timestamp)

            case "TASK_ASSIGNED":
                agent = event.target_agent
                agents = state.assigned_agents
                if agent and agent not in agents:
                    agents = [*agents, agent]
                state = replace(
                    state,
                    assigned_agents=agents,
                    current_step=event.payload.get("task_type"),
                    updated_at=event.timestamp,
                )

            case "TASK_COMPLETED":
                orig = event.payload.get("originating_event_type")
                processed = state.processed_event_types
                if orig and orig not in processed:
                    processed = [*processed, orig]
                state = replace(state, processed_event_types=processed, updated_at=event.timestamp)

            case "WORKFLOW_COMPLETED":
                state = replace(state, status=WorkflowStatus.COMPLETED, updated_at=event.timestamp)

            case "WORKFLOW_FAILED":
                state = replace(state, status=WorkflowStatus.FAILED, updated_at=event.timestamp)

        state = replace(state, last_event_id=event.event_id)

    return state
```

---

## Agent Polling Algorithm

```python
async def agent_event_loop(agent: BaseAgent, event_service: EventService, state_service: StateService) -> None:
    """
    Preconditions:
      - agent.subscribed_event_types is non-empty
      - event_service and state_service are connected

    Loop Invariant:
      - last_seen advances monotonically
      - No event is processed twice
    """
    last_seen: datetime | None = None

    while True:
        filters = EventFilters(
            workflow_id=agent.workflow_id,
            since=last_seen,
        )
        events = await event_service.query(filters)

        for event in events:
            # Guard 1: subscription filter
            if event.event_type not in agent.subscribed_event_types:
                last_seen = event.timestamp
                continue

            # Guard 2: already processed in this workflow
            state = await state_service.get_current(event.workflow_id)
            if event.event_type in state.processed_event_types:
                last_seen = event.timestamp
                continue

            # Guard 3: not expected at this workflow step
            if state.pending_event_types and event.event_type not in state.pending_event_types:
                last_seen = event.timestamp
                continue

            # Guard 4: causation loop detection
            if agent.agent_id in [str(uid) for uid in event.causation_chain]:
                await agent.emit_event(
                    event_type="TASK_FAILED",
                    payload={"reason": "recursion_loop_detected", "event_id": str(event.event_id)},
                    causation_chain=event.causation_chain,
                )
                last_seen = event.timestamp
                continue

            # Route by mode
            await agent.route_event(event)
            last_seen = event.timestamp

        await asyncio.sleep(POLL_INTERVAL)
```

---

## Atomic Claim Implementation

The `event_claims` table has a unique constraint on `event_id`. The claim operation uses `INSERT ... ON CONFLICT DO NOTHING` and checks the affected row count:

```python
async def try_claim(self, event_id: UUID, agent_id: str) -> bool:
    """
    Returns True if this agent won the claim (first writer wins).
    Returns False if another agent already holds the claim.
    Never raises on conflict — conflict is the expected concurrent case.
    """
    stmt = (
        pg_insert(EventClaimRow)
        .values(event_id=event_id, agent_id=agent_id, claimed_at=datetime.utcnow())
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    result = await self._session.execute(stmt)
    await self._session.commit()
    return result.rowcount == 1
```

---

## Orchestrator Decision Loop

```python
async def run_loop(self, workflow_id: str) -> None:
    """
    Loop Invariant: state reflects all events appended so far.
    Every iteration reads fresh state — no local caching.
    """
    while True:
        state = await self._state_service.get_current(workflow_id)

        if state.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            break

        decision = self.decide(state)

        match decision.action:
            case "ASSIGN_TASK":
                event = Event(
                    workflow_id=workflow_id,
                    conversation_id=state.conversation_id,
                    event_type=EventType.TASK_ASSIGNED,
                    source_agent="orchestrator",
                    target_agent=decision.agent_id,
                    routing_mode=RoutingMode.DIRECTED,
                    payload=decision.task_payload,
                )
                await self._event_service.append(event)

            case "COMPLETE":
                await self._event_service.append(Event(
                    workflow_id=workflow_id,
                    conversation_id=state.conversation_id,
                    event_type=EventType.WORKFLOW_COMPLETED,
                    source_agent="orchestrator",
                    payload={"summary": decision.summary},
                ))
                break

            case "FAIL":
                await self._event_service.append(Event(
                    workflow_id=workflow_id,
                    conversation_id=state.conversation_id,
                    event_type=EventType.WORKFLOW_FAILED,
                    source_agent="orchestrator",
                    payload={"reason": decision.reason},
                ))
                break

        await asyncio.sleep(POLL_INTERVAL)
```

---

## Local Docker Compose Setup

```yaml
# docker-compose.yml
version: "3.9"
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: agentmesh
      POSTGRES_PASSWORD: agentmesh
      POSTGRES_DB: agentmesh
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentmesh"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

---

## Error Handling

| Scenario | Trigger | Response | Recovery |
|----------|---------|----------|----------|
| Invalid event schema | Missing required field | `EventValidationError` → HTTP 422 | Agent catches, emits `TASK_FAILED` |
| Unknown event type | `event_type` not in registry | `UnknownEventTypeError` → HTTP 422 | Caller fixes event type |
| Unknown agent | `source_agent` not registered | `UnknownAgentError` → HTTP 422 | Caller uses registered agent ID |
| Duplicate event | Same `event_id` submitted twice | Return existing event (idempotent) | Transparent to caller |
| MCP unavailable | DB connection lost | `MCPUnavailableError` → HTTP 503 | Caller retries with exponential backoff |
| Causation loop | `event_id` in own causation chain | `CausationLoopError` → HTTP 422 | Agent emits `TASK_FAILED` with reason |
| Workflow conflict | `workflow_id` already started | `WorkflowConflictError` → HTTP 409 | Caller uses a new `workflow_id` |
| Workflow not found | No events for `workflow_id` | `WorkflowNotFoundError` → HTTP 404 | Caller verifies workflow was started |
| Claim conflict | Concurrent claim attempt loses | `try_claim` returns `False` | Agent skips event silently |
| Agent execute failure | Unhandled exception in `execute()` | Agent catches, emits `TASK_FAILED` | Orchestrator decides retry/fail |

---

## Testing Strategy

### Unit Tests
Each service is tested in isolation with fake/mock repositories — no real database:
- `EventService`: append, query, idempotency, validation errors
- `StateService`: projection for all event types, determinism, empty list
- `OrchestratorService`: decision logic for each state combination, `start_workflow` conflict

### API Tests
Every route tested with `httpx.AsyncClient` + `ASGITransport`:
- Happy path status codes and response schemas
- Validation errors (422) for missing/invalid fields
- Business logic errors (409, 404, 503)

### Property-Based Tests (Hypothesis)
State projection invariants with at least 100 examples:
- Idempotency: same event list → same state
- Monotonicity: more events never remove `processed_event_types` entries
- Completeness: every event reflected in projected state
- `last_event_id` always equals last event's `event_id`

### Integration Tests
Full workflow against a real PostgreSQL test database:
- Complete job-search workflow from start to COMPLETED
- Replay: `project_state(replay(wf_id)) == get_current(wf_id)`
- Concurrent claim: exactly 1 of 5 concurrent `try_claim` calls succeeds
- Idempotency: appending same event twice → exactly one DB row
- Loop prevention: agent in causation chain → `TASK_FAILED` emitted

---

## Correctness Properties

### Property 1: Append-Only Event Store
Events are never modified or deleted. For all `event_id`: once stored, `get_events()` always returns the same event for that ID.

**Validates: Requirements 5.1, 5.2**

### Property 2: State Reconstructability
Workflow state is fully reconstructable from the event log. For all `workflow_id`: `project_state(get_events(workflow_id)) == get_state(workflow_id)`.

**Validates: Requirements 6.9, 13.2**

### Property 3: No Direct Agent-to-Agent Calls
Agents never call each other directly. For all agents A and B: A communicates with B only via MCP events.

**Validates: Requirements 11.1, 12.2**

### Property 4: Every Decision Produces an Event
Every orchestrator decision is recorded. For all decisions `d`: there exists an event `e` where `e.source_agent == "orchestrator"` and `e` reflects `d`.

**Validates: Requirements 12.2, 12.3, 12.4**

### Property 5: Mandatory Identifiers on Every Event
For all events `e`: `e.conversation_id` is non-empty AND `e.workflow_id` is non-empty.

**Validates: Requirements 1.2, 1.3, 3.2, 3.3**

### Property 6: Deterministic State Projection
State projection is a pure function. For all event lists `L`: `project_state(L)` always produces the same `WorkflowState`.

**Validates: Requirements 6.1, 6.8**

### Property 7: Claim Exclusivity
At most one agent processes a CLAIMED event. For all events `e` where `routing_mode == CLAIMED`: at most one agent `A` exists such that `try_claim(e.event_id, A.agent_id)` returns `True`. Guaranteed by unique constraint on `event_claims(event_id)`.

**Validates: Requirements 9.1, 9.4, 9.6, 9.7**

### Property 8: No Recursion Loops
For all events `e` and agents `A`: if `A.agent_id` appears in `e.causation_chain`, then `A` must not process `e`.

**Validates: Requirements 10.3, 10.4**

### Property 9: Idempotent Append
For all events `e`: appending `e` twice results in exactly one record in the `events` table. The second call returns the existing record.

**Validates: Requirements 14.2**


---

## Future Extension Notes

The following are **not implemented in v1** but the architecture explicitly supports them:

- **Redis Streams / Kafka**: The polling loop in `BaseAgent` and the `EventService.query` interface can be replaced with a stream consumer. Agent business logic does not change because agents interact only through the `EventService` interface.
- **Distributed agents**: Agents are stateless — they can run as separate processes or containers. All state lives in MCP.
- **Event schema versioning**: `EventType` enum and Pydantic schemas should be versioned (e.g., `v1/events`) to support schema evolution without breaking existing consumers.
- **Webhook / push delivery**: The `GET /events` polling endpoint can be supplemented with a WebSocket or SSE endpoint for push-based delivery without changing the storage layer.
