"""Abstract solver port for Algorithmic-Core pattern."""

from __future__ import annotations

import abc

from .models import ProblemInput, SolutionOutput


class OptimizationSolver(abc.ABC):
    """Abstract port representing a mathematical, heuristic, or algorithmic solver."""

    @property
    @abc.abstractmethod
    def solver_name(self) -> str:
        """Returns the identifier of this solver strategy."""
        ...

    @abc.abstractmethod
    def solve(self, problem: ProblemInput) -> SolutionOutput:
        """Computes a feasible or optimal solution for the problem.

        Args:
            problem: Immutable problem input and constraints.

        Returns:
            The computed SolutionOutput.
        """
        ...
