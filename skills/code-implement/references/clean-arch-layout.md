# Clean Architecture & Subsystem Packaging Rules

This guide defines the directory and structural invariants that the **Specialist Implementer (`/code-implement`)** must enforce.

---

## 1. Directory Structure

```
src/modules/<subsystem>/
├── __init__.py
├── openapi.yaml                 # Frozen external HTTP contract (Gate 2)
├── SPEC.md                      # Living design doc: Tech-Lead-seeded (Gate 2), implementer-maintained
├── domain/                      # PURE business logic & entities (NO I/O)
│   ├── __init__.py
│   ├── models.py                # Frozen domain dataclasses & StrEnums
│   ├── exceptions.py            # Custom domain exception classes
│   ├── <pattern_ports>.py       # abc.ABC ports (e.g. rules/base_rule.py, ports.py)
│   └── <coordinator>.py         # Engine / Dispatcher / Runner / Solver / StateMachine
├── adapters/                    # External infrastructure implementations
│   ├── __init__.py
│   ├── memory_repository.py     # In-memory test/dev implementation
│   └── firestore_repository.py  # Production database/GCP adapter
└── entrypoints/                 # Public entrypoints (FastAPI router / worker)
    ├── __init__.py
    └── app.py                   # FastAPI router mapping HTTP to domain coordinator
```

---

## 2. Invariants

### 1. Single Responsibility (1 Public Class Per File)
- Every Rule, Stage, State Machine, Repository Port, Adapter, or Service must live in its own dedicated Python file.
- Only `models.py` (dataclasses/enums) and `exceptions.py` (exception classes) may declare multiple public classes.
- Examples across patterns:
  - **Decision-List**: `domain/rules/validate_url.py` $\to$ `class ValidateUrlRule(Rule)`
  - **Repository-Service**: `domain/service.py` $\to$ `class LookupService`
  - **State-Machine**: `domain/state_machine.py` $\to$ `class StateMachine`
  - **Pipeline-Reducer**: `domain/pipeline.py` $\to$ `class PipelineRunner`
  - **Algorithmic-Core**: `domain/solver_engine.py` $\to$ `class SolverEngine`

### 2. Hexagonal Seams (Ports vs Adapters)
- `domain/` contains only pure Python standard library modules (`abc`, `dataclasses`, `enum`, `typing`, `datetime`, `math`, `uuid`).
- `domain/` **NEVER** imports external I/O libraries (e.g. `google-cloud-firestore`, `httpx`, `sqlalchemy`, `fastapi`).
- `adapters/` implements the `abc.ABC` interfaces defined in `domain/ports.py`.
- Concrete adapters are injected into domain coordinators at runtime.

### 3. Boundary Confinement
- The implementer can only create or edit files in:
  - `src/modules/<subsystem>/`
  - `tests/unit/<subsystem>/`
  - `tests/integration/<subsystem>/`
- Any file modification outside this boundary is rejected by `scripts/check_boundaries.py` and the `PreToolUse` hook `scripts/hook_boundary_guard.py`.

### 4. Blueprint Consumption Model (Never Copy Archetypes)
- The archetype blueprints (`archetypes/python-clean-arch/templates/patterns/<pattern>/`) serve as structural templates for class shapes and port signatures.
- Never copy the `archetypes/` tree into the user repository.
- Synthesize new, domain-specific modules directly into `src/modules/<subsystem>/domain/` populated by `SPEC.md`.
