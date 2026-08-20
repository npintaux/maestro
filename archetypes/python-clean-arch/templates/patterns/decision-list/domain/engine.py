"""Decision engine orchestrator evaluating an ordered sequence of rules."""

from __future__ import annotations

from collections.abc import Sequence

from .models import Decision, DecisionOutcome, EvaluationContext
from .rules.base_rule import Rule


class DecisionEngine:
    """Ordered rules engine executing business rules sequentially.

    Evaluates rules in prioritized sequence and returns the first matching Decision.
    If no rule matches, returns a default fallback Decision.
    """

    def __init__(self, rules: Sequence[Rule]) -> None:
        """Initializes the decision engine with an ordered sequence of rules.

        Args:
            rules: Sequence of Rule instances to evaluate in priority order.
        """
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[Rule, ...]:
        """Returns the registered sequence of rules."""
        return self._rules

    def evaluate(self, context: EvaluationContext) -> Decision:
        """Evaluates the context across all registered rules in order.

        Args:
            context: Domain evaluation context.

        Returns:
            The Decision from the first matching rule, or the default fallback Decision.
        """
        for rule in self._rules:
            decision = rule.evaluate(context)
            if decision is not None:
                return decision

        return Decision(
            outcome=DecisionOutcome.REVIEW,
            rule_id="DEFAULT_FALLBACK",
            reason="No explicit rule matched the provided context; routed to manual review.",
        )
