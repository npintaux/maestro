"""Base abstract rule definition for Decision-List pattern."""

from __future__ import annotations

import abc

from ..models import Decision, EvaluationContext


class Rule(abc.ABC):
    """Abstract base class representing a single business rule or decision policy.

    Subclasses implement a specific predicate and return a Decision when triggered.
    """

    @property
    @abc.abstractmethod
    def rule_id(self) -> str:
        """Returns the unique identifier for this rule (e.g., 'R1-HIGH-VALUE')."""
        ...

    @abc.abstractmethod
    def evaluate(self, context: EvaluationContext) -> Decision | None:
        """Evaluate the rule against the incoming domain context.

        Args:
            context: Immutable domain evaluation context.

        Returns:
            A Decision instance if the rule triggered, or None to yield to the next rule.
        """
        ...
