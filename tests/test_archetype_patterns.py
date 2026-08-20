"""Tests validating behavioral correctness of all 5 archetype pattern templates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_module(full_name: str, file_path: Path) -> Any:
    """Dynamically loads a module with proper __package__ hierarchy."""
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = full_name.rpartition(".")[0]
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


# Load Pattern 1: Decision-List
dl_base = ROOT / "archetypes/python-clean-arch/templates/patterns/decision-list"
dl_models = _load_module(
    "templates.patterns.decision_list.domain.models", dl_base / "domain/models.py"
)
dl_base_rule = _load_module(
    "templates.patterns.decision_list.domain.rules.base_rule", dl_base / "domain/rules/base_rule.py"
)
dl_engine = _load_module(
    "templates.patterns.decision_list.domain.engine", dl_base / "domain/engine.py"
)

Decision = dl_models.Decision
DecisionOutcome = dl_models.DecisionOutcome
EvaluationContext = dl_models.EvaluationContext
Rule = dl_base_rule.Rule
DecisionEngine = dl_engine.DecisionEngine

# Load Pattern 2: Repository-Service
repo_base = ROOT / "archetypes/python-clean-arch/templates/patterns/repository-service"
repo_models = _load_module(
    "templates.patterns.repository_service.domain.models", repo_base / "domain/models.py"
)
repo_exceptions = _load_module(
    "templates.patterns.repository_service.domain.exceptions", repo_base / "domain/exceptions.py"
)
repo_ports = _load_module(
    "templates.patterns.repository_service.domain.ports", repo_base / "domain/ports.py"
)
repo_service = _load_module(
    "templates.patterns.repository_service.domain.service", repo_base / "domain/service.py"
)
repo_adapters = _load_module(
    "templates.patterns.repository_service.adapters.memory_repository",
    repo_base / "adapters/memory_repository.py",
)

Entity = repo_models.Entity
DuplicateEntityError = repo_exceptions.DuplicateEntityError
EntityNotFoundError = repo_exceptions.EntityNotFoundError
InactiveEntityError = repo_exceptions.InactiveEntityError
EntityRepository = repo_ports.EntityRepository
LookupService = repo_service.LookupService
InMemoryEntityRepository = repo_adapters.InMemoryEntityRepository

# Load Pattern 3: State-Machine
sm_base = ROOT / "archetypes/python-clean-arch/templates/patterns/state-machine"
sm_models = _load_module(
    "templates.patterns.state_machine.domain.models", sm_base / "domain/models.py"
)
sm_exceptions = _load_module(
    "templates.patterns.state_machine.domain.exceptions", sm_base / "domain/exceptions.py"
)
sm_engine = _load_module(
    "templates.patterns.state_machine.domain.state_machine", sm_base / "domain/state_machine.py"
)

State = sm_models.State
Event = sm_models.Event
TransitionContext = sm_models.TransitionContext
InvalidStateTransitionError = sm_exceptions.InvalidStateTransitionError
StateMachine = sm_engine.StateMachine

# Load Pattern 4: Pipeline-Reducer
pr_base = ROOT / "archetypes/python-clean-arch/templates/patterns/pipeline-reducer"
pr_models = _load_module(
    "templates.patterns.pipeline_reducer.domain.models", pr_base / "domain/models.py"
)
pr_ports = _load_module(
    "templates.patterns.pipeline_reducer.domain.ports", pr_base / "domain/ports.py"
)
pr_pipeline = _load_module(
    "templates.patterns.pipeline_reducer.domain.pipeline", pr_base / "domain/pipeline.py"
)

PipelineContext = pr_models.PipelineContext
PipelineStage = pr_ports.PipelineStage
PipelineRunner = pr_pipeline.PipelineRunner

# Load Pattern 5: Algorithmic-Core
algo_base = ROOT / "archetypes/python-clean-arch/templates/patterns/algorithmic-core"
algo_models = _load_module(
    "templates.patterns.algorithmic_core.domain.models", algo_base / "domain/models.py"
)
algo_ports = _load_module(
    "templates.patterns.algorithmic_core.domain.ports", algo_base / "domain/ports.py"
)
algo_engine = _load_module(
    "templates.patterns.algorithmic_core.domain.solver_engine",
    algo_base / "domain/solver_engine.py",
)

ProblemInput = algo_models.ProblemInput
SolutionOutput = algo_models.SolutionOutput
OptimizationSolver = algo_ports.OptimizationSolver
SolverEngine = algo_engine.SolverEngine

# ---------------------------------------------------------------------------
# Pattern 1: Decision-List Tests
# ---------------------------------------------------------------------------


class MockHighValueRule(Rule):  # type: ignore[misc,valid-type]
    """Test rule triggering on high value accounts."""

    @property
    def rule_id(self) -> str:
        return "R1-HIGH-VALUE"

    def evaluate(self, context: Any) -> Any:
        if context.attributes.get("amount", 0) > 1000:
            return Decision(
                outcome=DecisionOutcome.ALLOW,
                rule_id=self.rule_id,
                reason="High value account auto-approved.",
            )
        return None


def test_decision_list_matching_rule() -> None:
    """Verifies that decision engine returns matching rule decision."""
    engine = DecisionEngine([MockHighValueRule()])
    context = EvaluationContext(entity_id="acc-1", attributes={"amount": 5000})
    decision = engine.evaluate(context)

    assert decision.outcome == DecisionOutcome.ALLOW
    assert decision.rule_id == "R1-HIGH-VALUE"
    assert "auto-approved" in decision.reason
    assert len(engine.rules) == 1


def test_decision_list_fallback_rule() -> None:
    """Verifies that decision engine returns fallback review decision on no match."""
    engine = DecisionEngine([MockHighValueRule()])
    context = EvaluationContext(entity_id="acc-2", attributes={"amount": 100})
    decision = engine.evaluate(context)

    assert decision.outcome == DecisionOutcome.REVIEW
    assert decision.rule_id == "DEFAULT_FALLBACK"


# ---------------------------------------------------------------------------
# Pattern 2: Repository-Service Tests
# ---------------------------------------------------------------------------


def test_repository_service_crud_and_lookup() -> None:
    """Verifies entity creation, lookup, and repository persistence."""
    repo = InMemoryEntityRepository()
    service = LookupService(repo)

    entity = Entity(entity_id="user-123", payload={"name": "Alice"})
    created = service.create_entity(entity)
    assert created.entity_id == "user-123"

    fetched = service.get_entity("user-123")
    assert fetched.payload["name"] == "Alice"

    # Test delete
    assert repo.delete("user-123") is True
    assert repo.delete("user-123") is False


def test_repository_service_duplicate_error() -> None:
    """Verifies DuplicateEntityError when creating existing entity."""
    repo = InMemoryEntityRepository()
    service = LookupService(repo)
    entity = Entity(entity_id="user-1")
    service.create_entity(entity)

    with pytest.raises(DuplicateEntityError, match="already exists"):
        service.create_entity(entity)


def test_repository_service_not_found_error() -> None:
    """Verifies EntityNotFoundError when entity does not exist."""
    repo = InMemoryEntityRepository()
    service = LookupService(repo)

    with pytest.raises(EntityNotFoundError, match="not found"):
        service.get_entity("nonexistent")


def test_repository_service_inactive_error() -> None:
    """Verifies InactiveEntityError when entity is deactivated."""
    repo = InMemoryEntityRepository()
    service = LookupService(repo)
    repo.save(Entity(entity_id="user-inactive", is_active=False))

    with pytest.raises(InactiveEntityError, match="is deactivated"):
        service.get_entity("user-inactive")


# ---------------------------------------------------------------------------
# Pattern 3: State-Machine Tests
# ---------------------------------------------------------------------------


def test_state_machine_valid_transitions() -> None:
    """Verifies valid state transitions through lifecycle."""
    fsm = StateMachine(current_state=State.DRAFT)
    ctx = TransitionContext(entity_id="order-1", actor_id="user-1")

    assert fsm.can_transition(Event.SUBMIT) is True
    assert fsm.can_transition(Event.APPROVE) is False

    new_state = fsm.trigger(Event.SUBMIT, ctx)
    assert new_state == State.SUBMITTED
    assert fsm.current_state == State.SUBMITTED

    fsm.trigger(Event.APPROVE, ctx)
    assert fsm.current_state == State.APPROVED


def test_state_machine_invalid_transition() -> None:
    """Verifies InvalidStateTransitionError on illegal event."""
    fsm = StateMachine(current_state=State.DRAFT)
    ctx = TransitionContext(entity_id="order-2", actor_id="user-1")

    with pytest.raises(InvalidStateTransitionError, match="Cannot trigger event 'APPROVE'"):
        fsm.trigger(Event.APPROVE, ctx)


def test_state_machine_guard_rejection() -> None:
    """Verifies guard function rejection raises InvalidStateTransitionError."""

    def deny_guard(state: Any, event: Any, context: Any) -> bool:
        return False

    fsm = StateMachine(current_state=State.DRAFT, guard_fn=deny_guard)
    ctx = TransitionContext(entity_id="order-3", actor_id="user-1")

    with pytest.raises(InvalidStateTransitionError, match="Guard condition rejected"):
        fsm.trigger(Event.SUBMIT, ctx)


# ---------------------------------------------------------------------------
# Pattern 4: Pipeline-Reducer Tests
# ---------------------------------------------------------------------------


class MockNormalizeStage(PipelineStage):  # type: ignore[misc,valid-type]
    """Test stage normalizing input strings."""

    @property
    def stage_name(self) -> str:
        return "normalize"

    def process(self, context: Any) -> Any:
        raw_text = str(context.data.get("text", ""))
        return context.with_data("text", raw_text.strip().lower())


class MockEnrichStage(PipelineStage):  # type: ignore[misc,valid-type]
    """Test stage enriching metadata."""

    @property
    def stage_name(self) -> str:
        return "enrich"

    def process(self, context: Any) -> Any:
        return context.with_data("word_count", len(context.data.get("text", "").split()))


class MockFailingStage(PipelineStage):  # type: ignore[misc,valid-type]
    """Test stage appending an error."""

    @property
    def stage_name(self) -> str:
        return "failing"

    def process(self, context: Any) -> Any:
        return context.with_error("Stage processing failed")


def test_pipeline_runner_success() -> None:
    """Verifies sequential transformation across pipeline stages."""
    runner = PipelineRunner([MockNormalizeStage(), MockEnrichStage()])
    initial = PipelineContext(pipeline_id="pipe-1", data={"text": "  Hello World  "})

    result = runner.run(initial)
    assert result.data["text"] == "hello world"
    assert result.data["word_count"] == 2
    assert len(result.errors) == 0
    assert len(runner.stages) == 2


def test_pipeline_runner_stops_on_error() -> None:
    """Verifies pipeline execution halts when error is recorded."""
    runner = PipelineRunner([MockFailingStage(), MockEnrichStage()])
    initial = PipelineContext(pipeline_id="pipe-2", data={"text": "test"})

    result = runner.run(initial)
    assert len(result.errors) == 1
    assert "Stage processing failed" in result.errors[0]
    assert "word_count" not in result.data


# ---------------------------------------------------------------------------
# Pattern 5: Algorithmic-Core Tests
# ---------------------------------------------------------------------------


class MockGreedySolver(OptimizationSolver):  # type: ignore[misc,valid-type]
    """Test solver implementing a dummy knapsack/allocation strategy."""

    @property
    def solver_name(self) -> str:
        return "greedy-allocator"

    def solve(self, problem: Any) -> Any:
        items = problem.parameters.get("items", [])
        return SolutionOutput(
            problem_id=problem.problem_id,
            is_feasible=True,
            objective_value=float(len(items) * 10),
            assignments={"selected": items},
        )


def test_algorithmic_core_solver_engine() -> None:
    """Verifies solver engine execution and telemetry generation."""
    solver = MockGreedySolver()
    engine = SolverEngine(solver)

    problem = ProblemInput(
        problem_id="prob-1",
        parameters={"items": ["item1", "item2", "item3"]},
    )
    solution = engine.execute(problem)

    assert solution.problem_id == "prob-1"
    assert solution.is_feasible is True
    assert solution.objective_value == 30.0
    assert solution.assignments["selected"] == ["item1", "item2", "item3"]
    assert solution.execution_duration_ms >= 0.0
