# Pattern 5: Algorithmic-Core (Dedicated Solver / Strategy)

> **Computational Shape**: Cohesive Algorithm / Mathematical Solver / Strategy Pattern.  
> **Applicability**: Graph traversal & shortest-path routing (Dijkstra, A*), AST parsers, compilers, resource scheduling, optimization solvers, ML inference scoring.

---

## 1. Architecture Overview
Encapsulates a single cohesive mathematical or domain algorithm behind a pure `Solver(abc.ABC)` or `Strategy(abc.ABC)` port. Protects the algorithm from artificial, awkward decomposition into fake "rules" while keeping it 100% pure and isolated from I/O.

```
Problem Input ──▶ [ Solver ABC Port ] ──▶ [ Pure Concrete Algorithm ] ──▶ Solution Output
```

---

## 2. Domain Models (`src/domain/models.py`)
```python
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProblemInput:
    """Immutable input describing the optimization problem."""

    nodes: Sequence[str]
    edges: Mapping[str, Mapping[str, float]]
    start_node: str
    target_node: str


@dataclass(frozen=True)
class Solution:
    """Computed solution output."""

    optimal_path: tuple[str, ...]
    total_cost: float
    iterations: int
```

---

## 3. Solver ABC Port (`src/domain/solver.py`)
```python
import abc
from .models import ProblemInput, Solution


class RouteSolver(abc.ABC):
    """Abstract port for routing and path optimization."""

    @abc.abstractmethod
    def solve(self, problem: ProblemInput) -> Solution:
        """Execute algorithmic resolution on the input problem."""
        ...
```

---

## 4. Concrete Algorithm (`src/domain/algorithms/dijkstra.py`)
```python
import heapq
from ..exceptions import UnreachableTargetError
from ..models import ProblemInput, Solution
from ..solver import RouteSolver


class DijkstraRouteSolver(RouteSolver):
    """Deterministic shortest-path calculation."""

    def solve(self, problem: ProblemInput) -> Solution:
        distances: dict[str, float] = {node: float("inf") for node in problem.nodes}
        distances[problem.start_node] = 0.0
        previous: dict[str, str | None] = {node: None for node in problem.nodes}
        queue: list[tuple[float, str]] = [(0.0, problem.start_node)]
        iterations = 0

        while queue:
            current_dist, current_node = heapq.heappop(queue)
            iterations += 1

            if current_node == problem.target_node:
                break

            if current_dist > distances[current_node]:
                continue

            for neighbor, weight in problem.edges.get(current_node, {}).items():
                new_dist = current_dist + weight
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    previous[neighbor] = current_node
                    heapq.heappush(queue, (new_dist, neighbor))

        if distances[problem.target_node] == float("inf"):
            raise UnreachableTargetError(f"Target '{problem.target_node}' is unreachable.")

        path: list[str] = []
        curr: str | None = problem.target_node
        while curr is not None:
            path.append(curr)
            curr = previous[curr]
        path.reverse()

        return Solution(
            optimal_path=tuple(path),
            total_cost=distances[problem.target_node],
            iterations=iterations,
        )
```

---

## 5. Test Focus
- **Known-answer cases**: hand-computed small graphs where the optimal path and cost are known.
- **Edge topologies**: single node, disconnected target (`UnreachableTargetError`), and equal-cost ties (deterministic tie-breaking).
- **Determinism**: identical input yields identical output across runs.
- **Purity & complexity**: the solver takes a `ProblemInput` and returns a `Solution` with no I/O; guard against pathological inputs if the SLO demands it.
