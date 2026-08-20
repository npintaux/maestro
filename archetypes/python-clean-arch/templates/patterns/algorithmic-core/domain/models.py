"""Domain models for Algorithmic-Core optimization pattern."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProblemInput:
    """Immutable input parameters and constraints defining the computational problem.

    Attributes:
        problem_id: Unique task identifier.
        parameters: Numerical parameters, matrices, or item collections.
        constraints: Upper/lower bounds, budget caps, or structural limits.
    """

    problem_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SolutionOutput:
    """Immutable computed solution and execution diagnostics.

    Attributes:
        problem_id: Identifier of the resolved problem.
        is_feasible: Whether an optimal or feasible solution was found.
        objective_value: Computed optimal objective score (e.g. cost, distance).
        assignments: Computed item/variable assignments or schedule.
        execution_duration_ms: Algorithmic solve time in milliseconds.
    """

    problem_id: str
    is_feasible: bool
    objective_value: float
    assignments: dict[str, Any] = field(default_factory=dict)
    execution_duration_ms: float = 0.0
