"""Deterministic Finite State Machine implementation."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .exceptions import InvalidStateTransitionError
from .models import Event, State, TransitionContext


class StateMachine:
    """Encapsulates state transitions, guard conditions, and transition side effects."""

    # Explicit transition matrix: (CurrentState, Event) -> TargetState
    _TRANSITION_TABLE: Mapping[tuple[State, Event], State] = {
        (State.DRAFT, Event.SUBMIT): State.SUBMITTED,
        (State.SUBMITTED, Event.APPROVE): State.APPROVED,
        (State.SUBMITTED, Event.REJECT): State.REJECTED,
        (State.APPROVED, Event.FULFILL): State.FULFILLED,
        (State.DRAFT, Event.CANCEL): State.CANCELLED,
        (State.SUBMITTED, Event.CANCEL): State.CANCELLED,
    }

    def __init__(
        self,
        current_state: State = State.DRAFT,
        guard_fn: Callable[[State, Event, TransitionContext], bool] | None = None,
    ) -> None:
        """Initializes the state machine.

        Args:
            current_state: Initial starting state.
            guard_fn: Optional guard predicate returning True if transition is permitted.
        """
        self._current_state = current_state
        self._guard_fn = guard_fn

    @property
    def current_state(self) -> State:
        """Returns the current state."""
        return self._current_state

    def can_transition(self, event: Event) -> bool:
        """Checks if an event is legally allowed from the current state without side effects.

        Args:
            event: The proposed Event trigger.

        Returns:
            True if the transition is valid and allowed, False otherwise.
        """
        return (self._current_state, event) in self._TRANSITION_TABLE

    def trigger(self, event: Event, context: TransitionContext) -> State:
        """Executes a state transition in response to an event.

        Args:
            event: The triggering Event.
            context: Contextual payload accompanying the transition.

        Returns:
            The new State after the transition completes.

        Raises:
            InvalidStateTransitionError: If the transition is illegal or fails guard check.
        """
        key = (self._current_state, event)
        if key not in self._TRANSITION_TABLE:
            raise InvalidStateTransitionError(self._current_state, event)

        if self._guard_fn is not None and not self._guard_fn(self._current_state, event, context):
            raise InvalidStateTransitionError(
                self._current_state,
                event,
                f"Guard condition rejected transition '{event.value}' "
                f"from '{self._current_state.value}'.",
            )

        target_state = self._TRANSITION_TABLE[key]
        self._current_state = target_state
        return self._current_state
