"""Domain models for Decision-List rules engine pattern."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class DecisionOutcome(StrEnum):
    """Enumeration of possible decision outcomes."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class EvaluationContext:
    """Immutable evaluation context passed to rule predicates.

    Attributes:
        entity_id: Identifier of the subject under evaluation.
        attributes: Key-value attributes describing the evaluation state.
        timestamp: Time of evaluation request (defaults to current UTC).
    """

    entity_id: str
    attributes: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Decision:
    """Immutable outcome produced by a triggered rule.

    Attributes:
        outcome: Decision outcome status (ALLOW, DENY, REVIEW).
        rule_id: Unique identifier of the rule that produced this decision.
        reason: Explanatory rationale for auditability and compliance.
        metadata: Additional contextual payload or policy versions.
    """

    outcome: DecisionOutcome
    rule_id: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
