"""Solver engine validating inputs and delegating to optimization strategies."""

from __future__ import annotations

import time

from .models import ProblemInput, SolutionOutput
from .ports import OptimizationSolver


class SolverEngine:
    """Orchestrates problem input validation and solver execution."""

    def __init__(self, solver: OptimizationSolver) -> None:
        """Initializes the engine with an injected solver strategy.

        Args:
            solver: OptimizationSolver implementation to execute.
        """
        self._solver = solver

    def execute(self, problem: ProblemInput) -> SolutionOutput:
        """Validates problem constraints and invokes the solver.

        Args:
            problem: Immutable ProblemInput to solve.

        Returns:
            SolutionOutput containing computed assignments and execution metrics.
        """
        start_time = time.perf_counter()
        solution = self._solver.solve(problem)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return SolutionOutput(
            problem_id=solution.problem_id,
            is_feasible=solution.is_feasible,
            objective_value=solution.objective_value,
            assignments=solution.assignments,
            execution_duration_ms=duration_ms,
        )
