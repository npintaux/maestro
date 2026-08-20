"""Domain exceptions for State Machine pattern."""

from __future__ import annotations

from .models import Event, State


class StateMachineError(Exception):
    """Base exception for state machine transition violations."""


class InvalidStateTransitionError(StateMachineError):
    """Raised when an event cannot be applied to the current state."""

    def __init__(self, current_state: State, event: Event, message: str | None = None) -> None:
        """Initializes the transition error with state and event context.

        Args:
            current_state: The current state of the entity.
            event: The triggering event that failed.
            message: Optional additional detail.
        """
        detail = (
            message or f"Cannot trigger event '{event.value}' from state '{current_state.value}'."
        )
        super().__init__(detail)
        self.current_state = current_state
        self.event = event
