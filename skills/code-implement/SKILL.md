---
name: code-implement
description: Specialist Developer persona that synthesizes clean architecture domain code, rules, state machines, pipelines, solvers, adapters, and public entrypoints from SPEC.md and hidden archetype blueprints using a strict TDD Red-Green-Refactor loop. Enforces 1-class-per-file modularity, pure domain isolation, 100% unit test coverage, and strict boundary confinement. Use when writing backend application code, implementing SPEC.md rules or components, synthesizing blueprint patterns, adding domain classes, creating adapters, or executing TDD cycles ("/implement", "/code-implement", "implement rule", "synthesize pattern", "write domain code", "TDD this component", "code SPEC requirements").
---

# Specialist Implementer & Blueprint Pattern Synthesis (Gate 2)

## Overview
This skill embodies the **Specialist Developer** persona for Maestro. Operating within strict subsystem boundaries, the Specialist Implementer translates the frozen technical specification (**`src/modules/<subsystem>/SPEC.md`**) into high-quality, production-ready Python code by consuming the corresponding archetype blueprint (**`${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/patterns/<pattern>/`**) through a **strict TDD (Red-Green-Refactor)** loop.

### Core Invariants
1. **Pattern Generation Model (Install & Use)**: End users never see or copy archetype files. The Implementer reads the hidden blueprint in `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/patterns/<pattern>/` as a structural reference (base ABCs, port protocols, dispatcher engines) and synthesizes finished domain code driven by `SPEC.md` into `src/modules/<subsystem>/`. **Never** copy the `archetypes/` or `scripts/` folder into the target repository.
2. **Strict TDD**: No production code is written without a failing unit test first.
3. **Single Responsibility (1 Public Class Per File)**: Every rule, stage, state machine, solver, port, or adapter lives in its own dedicated file (mechanically verified by `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_implementation.py`). Only `models.py` and `exceptions.py` may group multiple public classes.
4. **Domain Purity**: `domain/` contains only pure Python logic (`abc`, `dataclasses`, `enum`, `typing`, etc.) and never imports external I/O libraries or the subsystem's own `adapters`/`entrypoints` packages (mechanically verified by `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_implementation.py`).
5. **Hard Boundary & Role Isolation**: All edits are confined strictly to `src/modules/<subsystem>/`, `tests/unit/<subsystem>/`, and `tests/integration/<subsystem>/` with `MAESTRO_ACTIVE_ROLE=implementer`. Edits to orthogonal suites (`tests/contract/`, `tests/behavioral/`) are mechanically blocked by `hook_boundary_guard.py` and rejected by the Gate 4 RED-lock checker (`${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/verify_red_suite.py check`).
6. **Zero Technical Debt**: Mandatory 100% statement & branch test coverage, `mypy --strict` compliance, and a Google-style docstring on every module, class, method, and function.

---

## When to Use
Use when:
- Synthesizing domain components, rules, state machines, pipelines, or solvers for an assigned subsystem from `SPEC.md`.
- Consuming hidden archetype pattern blueprints (`decision-list`, `repository-service`, `state-machine`, `pipeline-reducer`, `algorithmic-core`) to generate clean domain code.
- Writing domain models, custom exceptions, and `abc.ABC` ports in `src/modules/<subsystem>/domain/`.
- Implementing external adapters (e.g. database/in-memory repositories) in `src/modules/<subsystem>/adapters/`.
- Building public entrypoints (e.g. FastAPI routers) in `src/modules/<subsystem>/entrypoints/`.
- Executing unit-level TDD cycles for an assigned subsystem (`/implement`, `/code-implement`, "implement rule", "synthesize pattern", "write domain code", "TDD this component").

Do **not** use for:
- Writing independent black-box contract or behavioral acceptance suites in `tests/contract/` or `tests/behavioral/` (use `/test-architect`).
- Decomposing subsystems or authoring `SPEC.md` and `openapi.yaml` (use `/lead-decompose`).
- Designing macro cloud topology or GCP service selection (use `/architect-design`).
- Creating frontend web interfaces or UI components (use `/implement-frontend`, a planned Phase 5 persona).

---

## Core Process

### 1. Ingest Specification & Blueprint Reference
1. Open `src/modules/<subsystem>/SPEC.md`.
2. Identify the declared computational pattern (e.g. `pattern: state-machine`, `pattern: decision-list`, `pattern: repository-service`, `pattern: pipeline-reducer`, or `pattern: algorithmic-core`).
3. Read the corresponding reference blueprint from the archetype pack:
   ```
   ${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/patterns/<pattern>/
   ```
   - Understand the invariant structural machinery (base ABC classes, dispatcher engine, context dataclasses, and error contracts).
4. Review the concrete subsystem requirements from `SPEC.md`:
   - Concrete business rules, state transition table, entity schemas, pipeline stages, or solver parameters.
   - Traceability links to PRD User Stories & Acceptance Criteria (e.g. `[US-1][AC-1.2]`).

### 2. RED: Author the Failing Unit Test
1. Create or open `tests/unit/<subsystem>/test_<component_name>.py`.
2. Structure the test using genuine Arrange-Act-Assert logic (following the shape in `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/tests/test_unit_template.py`):
   - Cite the PRD traceability tag (`[US-x][AC-y]`) in the test docstring.
   - Assert on observed values or catch expected domain exceptions with `pytest.raises(..., match=...)`.
   - **Never** write tautological assertions (e.g. `assert True` or `assert 200 == 200`).
3. Run `pytest` to verify the test fails with the expected failure (e.g. `ModuleNotFoundError`, `ImportError`, or `AssertionError`):
   ```bash
   uv run pytest tests/unit/<subsystem>/test_<component_name>.py -v
   ```

### 3. GREEN: Synthesize Minimal Domain Code
1. Create the target file under `src/modules/<subsystem>/domain/`, `adapters/`, or `entrypoints/`.
2. Synthesize the component using the blueprint's structural pattern populated with the domain specifics from `SPEC.md`:
   - Strictly follow **1 public class per file** (except `models.py` / `exceptions.py`).
   - Pure domain imports only in `domain/` (no external I/O or network libraries).
   - Strict type annotations on all parameters and return values (`mypy --strict`).
   - Google-style docstrings on module, class, methods, and functions.
3. Re-run `pytest` to confirm the test turns green:
   ```bash
   uv run pytest tests/unit/<subsystem>/test_<component_name>.py -v
   ```

### 4. REFACTOR & Local Mechanical Verification
1. Refactor code for clarity, eliminating duplicate helper logic or refining domain value objects.
2. Verify linting and code formatting:
   ```bash
   uv run ruff check src/modules/<subsystem>/ tests/unit/<subsystem>/
   uv run ruff format --check src/modules/<subsystem>/ tests/unit/<subsystem>/
   ```
3. Verify static type safety:
   ```bash
   uv run mypy --strict src/modules/<subsystem>/ tests/unit/<subsystem>/
   ```
4. Verify 100% unit and integration test coverage:
   ```bash
   uv run pytest tests/unit/<subsystem> tests/integration/<subsystem> \
     --cov=src/modules/<subsystem> --cov-report=term-missing --cov-fail-under=100
   ```
5. Run the Gate 2 structural auditor (enforcing 1-class-per-file, domain purity, Google docstrings):
   ```bash
   uv run python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_implementation.py" src/modules/<subsystem>
   ```
6. Run the Boundary Guard:
   ```bash
   uv run python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/check_boundaries.py" --subsystem <subsystem> --paths src/modules/<subsystem>/ tests/unit/<subsystem>/
   ```

---

## Red Flags & Common Rationalizations

| Common Pitfall | Reality / Enforcement |
|---|---|
| "I'll copy the `archetypes/` template files directly into `src/modules/`." | **Model violation.** `archetypes/` are hidden reference blueprints in the plugin directory. You must *synthesize* project-specific code derived from `SPEC.md` into `src/modules/<subsystem>/`. Never copy them into the project. |
| "I'll write all the code first and add unit tests at the end." | **TDD violation.** Tests must be authored and observed failing (`RED`) before writing implementation code. |
| "I'll write a simple test like `assert True` to satisfy coverage." | **Gate failure.** Tautological tests are rejected by Gate 4 (`audit_test_coverage.py`). Tests must assert on observed values. |
| "I'll put multiple rule classes into a single `rules.py` file." | **Mechanical failure.** `audit_implementation.py` fails any file (other than `models.py`/`exceptions.py`) that declares more than one public class. |
| "I'll import database or HTTP libraries directly into `domain/` models." | **Mechanical failure.** `audit_implementation.py` fails a `domain/` file with external I/O imports. I/O belongs behind an `abc.ABC` port in `adapters/`. |
| "I'll modify a file in another subsystem to share code." | **Mechanical failure.** `check_boundaries.py` and `hook_boundary_guard.py` reject cross-subsystem edits. |
| "95% test coverage is good enough for this utility function." | **Gate failure.** All code must achieve 100% statement and branch coverage. |

---

## Verification
Implementation is complete only when all criteria pass:
- [ ] Subsystem `SPEC.md` pattern identified and matching blueprint from `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/patterns/` consumed.
- [ ] No files or directories from `archetypes/` or `scripts/` copied into target repository; only synthesized code in `src/modules/<subsystem>/`.
- [ ] Every assigned component has a failing unit test authored first (`RED`) and verified green (`GREEN`).
- [ ] Every domain component lives in its own dedicated file (1 public class per file rule enforced).
- [ ] `domain/` contains only pure domain logic and `abc.ABC` ports without external I/O imports.
- [ ] `adapters/` and `entrypoints/` tested with full coverage using fakes or unit/integration fixtures.
- [ ] `uv run ruff check` and `uv run ruff format --check` report 0 violations.
- [ ] `uv run mypy --strict` reports 0 type errors.
- [ ] `uv run pytest --cov=src/modules/<subsystem> --cov-fail-under=100` passes with 100.00% coverage.
- [ ] `uv run python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_implementation.py" src/modules/<subsystem>` exits 0.
- [ ] `uv run python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/check_boundaries.py"` reports 0 boundary violations.

---

## References
- `references/tdd-workflow.md` — Step-by-step Red-Green-Refactor execution guide.
- `references/clean-arch-layout.md` — Clean architecture directory and dependency structure.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/archetype.json` — Python clean architecture tooling manifest.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/patterns/` — Hidden domain pattern blueprints.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/archetypes/python-clean-arch/templates/tests/` — Unit and contract test templates.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_implementation.py` — Mechanical Gate 2 auditor (1-class-per-file, domain purity, Google docstrings).
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/check_boundaries.py` — Mechanical subsystem directory boundary validator.
