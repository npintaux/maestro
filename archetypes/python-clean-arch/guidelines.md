# Python Clean Architecture Coding Guidelines

This guide details the strict engineering and design rules enforced mechanically across all Python code generated or maintained within Maestro.

---

## 1. Single Responsibility: One Public Class Per File

Every public class, port interface, domain rule, service, or adapter must reside in its own dedicated module file:
* **Rule**: `class HighValueRule` belongs in `domain/rules/high_value_rule.py`.
* **Prohibited**: Putting multiple rule classes (e.g. `RuleA`, `RuleB`, `RuleC`) in a single `rules.py` file.
* **Exceptions**: Tightly coupled private helper classes or internal enum definitions that are solely consumed by the primary class may reside in the same file if marked private (`_PrivateHelper`).

---

## 2. 100% Google-Style Docstrings

All Python modules, classes, public methods, and functions must contain comprehensive Google-style docstrings:

```python
"""Module docstring explaining domain purpose and design invariants."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransactionContext:
    """Represents the immutable evaluation context for financial transactions.

    Attributes:
        account_id: Unique account identifier string.
        amount_cents: Transaction amount represented in integer cents.
        currency: Three-letter ISO 4217 currency code.
    """

    account_id: str
    amount_cents: int
    currency: str = "USD"

    def is_micro_transaction(self) -> bool:
        """Determines whether the transaction amount qualifies as a micro-charge.

        Returns:
            True if transaction is under $5.00 (500 cents), False otherwise.
        """
        return self.amount_cents < 500
```

### Docstring Requirements:
- **Module docstring**: Summary of file responsibility and architectural layer.
- **Class docstring**: Role, invariants, and `Attributes:` list for dataclasses/models.
- **Method docstring**: Purpose, `Args:`, `Returns:`, and `Raises:` when exceptions can occur.

---

## 3. Strict Static Typing (`mypy --strict`)

Every function signature and class attribute must be fully type-annotated:
* Use `from __future__ import annotations` at the top of every file.
* Use standard Python 3.10+ union syntax (`str | None` instead of `Optional[str]`).
* Use generic built-ins (`list[str]`, `dict[str, Any]`, `Sequence[int]`).
* Avoid bare `Any` unless wrapping dynamic serialization boundaries.
* Never use `# type: ignore` without an accompanying explanatory comment and architectural rationale.

---

## 4. Pure Domain Core & Dataclass Immutability

Domain models represent the heart of the business logic and must remain free of framework clutter:
* Use `@dataclass(frozen=True)` for all domain models and values.
* Never perform network I/O, filesystem operations, or database queries inside domain models or rule evaluators.
* All I/O must be delegated to secondary adapter ports (`domain/ports.py` implemented in `adapters/`).

---

## 5. Pattern Selection & Composition

Tech Leads select exactly one primary computational pattern per subsystem:

1. **Decision-List** (`Rule(abc.ABC)` + `engine.py`):
   - For predicate evaluation, risk scoring, discount engines, approval workflows.
   - Rules are ordered; engine stops on first match or accumulates rule outcomes.
2. **Repository-Service** (`Repository(abc.ABC)` + `service.py`):
   - For CRUD, key-value lookup, entity resolution, and document stores.
3. **State-Machine** (`State`, `Event`, `TransitionTable` + `state_machine.py`):
   - For order lifecycles, booking workflows, ticket states, and protocol sessions.
4. **Pipeline-Reducer** (`PipelineStage(abc.ABC)` + `pipeline.py`):
   - For ETL data processing, telemetry enrichment, batch data transformation.
5. **Algorithmic-Core** (`Solver(abc.ABC)` + `solver.py`):
   - For optimization algorithms, pathfinding, bin-packing, mathematical models.

---

## 6. Test-Driven Development (TDD) Discipline

All production code must be authored using the **Red-Green-Refactor** workflow:
1. **Red**: Author a failing unit test asserting the exact behavior or edge case.
2. **Green**: Write the minimal domain code required to pass the test.
3. **Refactor**: Clean up and optimize while maintaining 100% passing tests.
4. **Coverage**: 100% statement and branch coverage is strictly required. No uncovered branches or omitted exception checks.
