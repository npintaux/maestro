"""Domain models for Finite State Machine pattern."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class State(StrEnum):
    """Lifecycle states for a domain entity."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class Event(StrEnum):
    """Triggers causing transitions between states."""

    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    FULFILL = "FULFILL"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class TransitionContext:
    """Context and payload associated with an attempted state transition.

    Attributes:
        entity_id: The identifier of the entity undergoing transition.
        actor_id: Identifier of the user or system initiating the transition.
        payload: Metadata and parameters supporting the transition.
        timestamp: Time of transition attempt in UTC.
    """

    entity_id: str
    actor_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
