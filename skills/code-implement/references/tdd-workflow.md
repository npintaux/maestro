# Strict TDD (Red-Green-Refactor) Workflow

This workflow is the mandatory execution cycle for the **Specialist Implementer (`/code-implement`)**. Every component, rule, stage, state machine, or solver from `SPEC.md` must be built following this exact progression.

---

## The Invariant
> **No implementation code is written without a failing unit test first.**
> You must run the test to see it fail (`RED`) with the expected reason before writing production code.

---

## Step-by-Step Cycle

### Step 1: Ingest Blueprint & Subsystem Specification
1. Open `src/modules/<subsystem>/SPEC.md` and read the assigned `pattern:` (e.g. `state-machine`).
2. Consult the matching hidden blueprint in `archetypes/python-clean-arch/templates/patterns/<pattern>/` to inspect the structural scaffolding (ports, base classes, dispatcher machinery).
3. Identify the specific component or rule to implement:
   - Target class name & file path (e.g. `src/modules/<subsystem>/domain/rules/validate_url.py`)
   - Target PRD User Story / Acceptance Criterion (e.g. `[US-1][AC-1.2]`)
   - Input dataclass / parameters and expected return type or exception

### Step 2: RED — Author the Failing Test
Create or update `tests/unit/<subsystem>/test_<component>.py`:
1. Write a focused unit test covering the specific behavior or boundary condition using Arrange-Act-Assert.
2. Include full type annotations and Google-style docstrings referencing the PRD story (`[US-x][AC-y]`).
3. Assert on actual returned outputs or expected domain exceptions (`pytest.raises(..., match=...)`).
4. Run `pytest` to verify the failure:
   ```bash
   uv run pytest tests/unit/<subsystem>/test_<component>.py -v
   ```
5. Verify the test fails because the component does not yet exist or the logic is unimplemented (not due to syntax error).

### Step 3: GREEN — Minimal Implementation
Create the target file under `src/modules/<subsystem>/domain/`, `adapters/`, or `entrypoints/`:
1. Write the minimal code required to make the test pass, reproducing the blueprint's invariant machinery with the domain specifics from `SPEC.md`.
2. Ensure exactly **1 public class per file** (only `models.py` / `exceptions.py` may group several).
3. Use strict type annotations everywhere (`mypy --strict`).
4. Add a Google-style docstring to the module and every public class and method.
5. Run `pytest` to verify it passes:
   ```bash
   uv run pytest tests/unit/<subsystem>/test_<component>.py -v
   ```

### Step 4: REFACTOR & Verify Gates
Once the test is green:
1. Clean up internal structure, extract constants, or refine naming without changing external behavior.
2. Verify formatting and linting:
   ```bash
   uv run ruff check src/modules/<subsystem>/ tests/unit/<subsystem>/
   uv run ruff format --check src/modules/<subsystem>/ tests/unit/<subsystem>/
   ```
3. Verify static type safety:
   ```bash
   uv run mypy --strict src/modules/<subsystem>/ tests/unit/<subsystem>/
   ```
4. Verify 100% test coverage:
   ```bash
   uv run pytest tests/unit/<subsystem> tests/integration/<subsystem> --cov=src/modules/<subsystem> --cov-fail-under=100
   ```
5. Verify the structural invariants (1-public-class-per-file, domain purity, docstring presence):
   ```bash
   uv run python3 scripts/audit_implementation.py src/modules/<subsystem>
   ```
6. Verify boundary isolation:
   ```bash
   uv run python3 scripts/check_boundaries.py --subsystem <subsystem> --paths src/modules/<subsystem>/ tests/unit/<subsystem>/
   ```
