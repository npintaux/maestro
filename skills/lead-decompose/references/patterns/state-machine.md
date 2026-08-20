# Pattern 3: State-Machine (Stateful Workflow / Saga / Lifecycle)

> **Computational Shape**: Event-Driven State Transitions with explicit state matrices and compensation.  
> **Applicability**: Order processing (`Pending -> Reserved -> Charged -> Shipped`), booking reservations, multi-step asynchronous sagas, payment settlement flows.

---

## 1. Architecture Overview
Models entities with well-defined lifecycles. Incoming domain events trigger deterministic state transitions governed by a transition matrix. Rejects invalid transitions with explicit errors and supports rollback/compensation.

```
State: PENDING ──[ EVENT: PAY ]──▶ State: CHARGED ──[ EVENT: SHIP ]──▶ State: COMPLETED
      │                                 │
      └──[ EVENT: CANCEL ]──────────────┴──▶ State: CANCELLED (Compensate)
```

---

## 2. Domain Models & Enums (`src/domain/models.py`)
```python
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class State(Enum):
    """Explicit lifecycle states."""

    PENDING = auto()
    RESERVED = auto()
    CHARGED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class EventType(Enum):
    """Supported lifecycle event types."""

    RESERVE = auto()
    CHARGE = auto()
    SHIP = auto()
    CANCEL = auto()


@dataclass(frozen=True)
class Event:
    """Domain event triggering a state transition."""

    event_type: EventType
    entity_id: str
    payload: Optional[dict[str, object]] = None


@dataclass(frozen=True)
class TransitionResult:
    """Outcome of a state transition."""

    success: bool
    from_state: State
    to_state: State
    message: str
```

---

## 3. Transition Table & State Machine (`src/domain/state_machine.py`)
```python
from .exceptions import InvalidTransitionError
from .models import Event, EventType, State, TransitionResult

# Mapping: (CurrentState, EventType) -> NextState
TRANSITION_MATRIX: dict[tuple[State, EventType], State] = {
    (State.PENDING, EventType.RESERVE): State.RESERVED,
    (State.RESERVED, EventType.CHARGE): State.CHARGED,
    (State.CHARGED, EventType.SHIP): State.COMPLETED,
    (State.PENDING, EventType.CANCEL): State.CANCELLED,
    (State.RESERVED, EventType.CANCEL): State.CANCELLED,
    (State.CHARGED, EventType.CANCEL): State.CANCELLED,
}


class WorkflowStateMachine:
    """Evaluates and executes valid state transitions."""

    def transition(self, current_state: State, event: Event) -> TransitionResult:
        key = (current_state, event.event_type)
        if key not in TRANSITION_MATRIX:
            raise InvalidTransitionError(
                f"Cannot transition from {current_state.name} with event {event.event_type.name}."
            )

        next_state = TRANSITION_MATRIX[key]
        return TransitionResult(
            success=True,
            from_state=current_state,
            to_state=next_state,
            message=f"Transitioned from {current_state.name} to {next_state.name}.",
        )
```

---

## 4. Status Code Mapping
Map an illegal transition to **`409 Conflict`**, not `422`: the request itself is well-formed, but it conflicts with the entity's *current lifecycle state* (a state/resource conflict). Reserve `422 Unprocessable Entity` for semantically invalid payloads. In `SPEC.md`'s error taxonomy, `InvalidTransitionError → 409 Conflict → STATE_CONFLICT`.

---

## 5. Test Focus
- **Legal transition matrix**: table-driven test asserting every `(state, event)` in `TRANSITION_MATRIX` yields the expected next state.
- **Illegal transitions raise `InvalidTransitionError`**: every `(state, event)` *absent* from the matrix must raise (→ `409`), not silently pass.
- **Idempotency / terminal states**: events applied to terminal states (`COMPLETED`, `CANCELLED`) are rejected.
- **Purity**: the machine computes the next state without I/O; durable load/save is exercised through the injected `repository-service` port.
