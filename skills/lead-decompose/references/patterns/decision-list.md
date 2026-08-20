# Pattern 1: Decision-List (Rules Engine)

> **Computational Shape**: Request-In / Decision-Out with pure predicate evaluations.  
> **Applicability**: Validation, policy authorization, eligibility/underwriting, fraud/risk screening, tiered pricing gates, content moderation.

---

## 1. Architecture Overview
A linear pipeline of independent, single-responsibility `Rule(abc.ABC)` subclasses evaluated by a central `engine.py` dispatcher. Supports short-circuiting on failure.

```
Request ──▶ [ Rule R1: Validate ] ──▶ [ Rule R2: CheckPolicy ] ──▶ [ Rule R3: Calculate ] ──▶ Decision
                    │                              │                              │
              (Fail -> 400)                  (Fail -> 403)                  (Fail -> 422)
```

---

## 2. Domain Models (`src/domain/models.py`)
```python
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EvaluationRequest:
    """Immutable input payload for decision evaluation."""

    request_id: str
    entity_id: str
    attributes: dict[str, object]


@dataclass(frozen=True)
class Decision:
    """Immutable result of rule execution."""

    is_allowed: bool
    status_code: int
    reason: str
    details: Optional[dict[str, object]] = None
```

---

## 3. Rule ABC (`src/domain/rules/base.py`)
```python
import abc
from ..models import Decision, EvaluationRequest


class Rule(abc.ABC):
    """Abstract Base Class for individual decision predicates."""

    @property
    @abc.abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier (e.g., 'R1', 'R2')."""
        ...

    @abc.abstractmethod
    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate business rule against request."""
        ...
```

---

## 4. Decision Engine (`src/domain/engine.py`)
```python
from collections.abc import Sequence
from .models import Decision, EvaluationRequest
from .rules.base import Rule


class DecisionEngine:
    """Composed dispatcher executing ordered rule sequence."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules = tuple(rules)

    def evaluate(self, request: EvaluationRequest) -> Decision:
        for rule in self._rules:
            decision = rule.evaluate(request)
            if not decision.is_allowed:
                return decision
        return Decision(is_allowed=True, status_code=200, reason="All rules passed.")
```

---

## 5. Test Focus
- **Each `Rule` in isolation**: one focused test per rule for its pass and fail branches, asserting the exact `status_code` (e.g. 400 vs 403 vs 422).
- **Short-circuit ordering**: the engine returns the *first* failing rule's `Decision` and does not evaluate later rules.
- **All-pass path**: an allowed request returns `is_allowed=True` with `200`.
- **Injected ports**: rules that consult external state are tested with a fake `Repository` port, not a live datastore.
