# AgentMesh — Coding Standards

## Core Principles

These rules apply to all Python code in the AgentMesh project. They are enforced by code review and, where possible, by `ruff` and `mypy`.

---

## Type Hints

**Use type hints everywhere — no exceptions.**

- All function parameters must be typed
- All return types must be annotated (including `-> None`)
- All class attributes must be typed
- Use `from __future__ import annotations` at the top of files where forward references are needed
- Prefer `X | Y` union syntax (Python 3.10+) over `Union[X, Y]`
- Use `TypeAlias` for complex type aliases
- Never use `Any` unless absolutely unavoidable, and always add a comment explaining why

```python
# Good
async def append_event(event: Event) -> EventRecord:
    ...

# Bad
async def append_event(event):
    ...
```

---

## Dependency Injection

**Prefer dependency injection over module-level singletons.**

- Services receive their dependencies (repositories, other services, config) via `__init__` parameters
- FastAPI route handlers receive services via `Depends()`
- Agents receive their tools and LLM providers via `__init__` parameters
- Never import and use a concrete dependency directly inside a function body if it can be injected

```python
# Good
class EventService:
    def __init__(self, repo: EventRepository) -> None:
        self._repo = repo

# Bad
class EventService:
    async def append(self, event: Event) -> EventRecord:
        repo = EventRepository(get_db_session())  # hidden dependency
        ...
```

---

## Domain Models vs ORM Models

**Keep domain models separate from ORM models.**

- `src/core/models.py` contains Pydantic v2 domain models — these are the canonical data shapes used throughout the service and agent layers
- `src/storage/models.py` contains SQLAlchemy ORM models — these are only used in the storage layer
- The repository layer is responsible for converting between ORM rows and domain models
- Service and agent code must never import SQLAlchemy ORM models directly

```python
# Good — service works with domain models
async def get_workflow_state(self, workflow_id: UUID) -> WorkflowState:
    return await self._repo.get_state(workflow_id)  # repo returns domain model

# Bad — service touches ORM model
from src.storage.models import CurrentStateRow
async def get_workflow_state(self, workflow_id: UUID) -> CurrentStateRow:
    ...
```

---

## Agent State

**Avoid hidden state in agents.**

- Agent instances must not accumulate mutable state between polling cycles
- Any state an agent needs between cycles must be stored in MCP (via events), not in instance variables
- Agent `__init__` may store configuration and injected dependencies, but not workflow state
- If an agent crashes and restarts, it must be able to resume correctly by replaying events from MCP

---

## Function Size and Testability

**Keep functions small and testable.**

- A function should do one thing
- If a function is hard to test, it is probably doing too much — split it
- Aim for functions that fit on a screen (roughly 20–40 lines)
- Extract complex conditionals into named helper functions
- Pure functions (no side effects, deterministic output) are preferred for business logic

---

## Route Handlers

**Do not put business logic inside FastAPI route handlers.**

Route handlers must only:
1. Validate the incoming request (Pydantic does this automatically)
2. Call the appropriate service method
3. Return the response

```python
# Good
@router.post("/events", response_model=EventResponse, status_code=201)
async def append_event(
    body: AppendEventRequest,
    service: EventService = Depends(get_event_service),
) -> EventResponse:
    event = await service.append(body.to_domain())
    return EventResponse.from_domain(event)

# Bad
@router.post("/events")
async def append_event(body: AppendEventRequest, db: AsyncSession = Depends(get_db)):
    # business logic directly in route handler
    existing = await db.execute(select(EventRow).where(...))
    if existing.scalar():
        raise HTTPException(...)
    ...
```

---

## Global Mutable State

**Do not introduce global mutable state.**

- No module-level mutable variables (lists, dicts, sets) that are modified at runtime
- No global caches unless they are explicitly thread-safe and documented
- Application configuration may be module-level but must be read-only after startup
- Use FastAPI's `lifespan` context manager for startup/shutdown resource management, not module-level side effects

---

## Docstrings

**Add docstrings for core interfaces and complex algorithms.**

Required for:
- All abstract base classes and Protocol definitions
- All public methods on service classes
- All repository interface methods
- Any function implementing a non-trivial algorithm (state projection, causation chain walking, claim logic)

Format: Google-style docstrings

```python
async def project_state(self, events: list[Event]) -> WorkflowState:
    """Project workflow state from an ordered list of events.

    This function is pure and deterministic: the same input always
    produces the same output. It must not perform I/O.

    Args:
        events: Ordered list of events for a single workflow_id,
                sorted by sequence_number ascending.

    Returns:
        The projected WorkflowState reflecting all events.

    Raises:
        InvalidEventSequenceError: If events are not from the same workflow_id
            or are not in sequence order.
    """
```

Optional but encouraged for:
- Non-obvious helper functions
- Any function where the "why" is not obvious from the code

---

## Error Handling

- Use domain exceptions from `src/core/exceptions.py` — never raise raw `Exception` or `ValueError` from service code
- FastAPI exception handlers in `main.py` convert domain exceptions to HTTP responses
- Never swallow exceptions silently — log and re-raise, or convert to a domain exception
- Use `try/except` narrowly around the specific operation that can fail, not around large blocks

---

## Imports

- Use absolute imports throughout (`from src.core.models import Event`, not relative `from ..core.models import Event`)
- Group imports: stdlib → third-party → local, separated by blank lines
- `ruff` enforces import ordering automatically

---

## Async

- All I/O-bound operations must be `async`
- Never use `time.sleep()` in async code — use `asyncio.sleep()`
- Never call blocking I/O (file reads, sync DB calls) from async functions without running in an executor
- Use `asyncio.gather()` for concurrent independent async operations
