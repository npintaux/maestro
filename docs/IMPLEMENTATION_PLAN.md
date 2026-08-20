# 🎼 Maestro: Python-First Implementation Plan

## Overview & Objective
This document outlines the step-by-step engineering implementation plan for **Maestro** (`maestro-plugin`). The primary goal is to build a fully functional, production-ready autonomous swarm orchestrator focusing on **Python 3.12+/3.13** as both the plugin runtime and the reference target application stack.

---

## Architecture & Component Mapping

```
/home/user/orchestrated-coding/
├── plugin.json                           # Plugin manifest (registers skills, references, and hooks)
├── hooks.json                            # Unbypassable lifecycle hooks (PreToolUse boundary guard, Stop gating)
├── resources/
│   ├── waf/
│   │   └── gcp_waf.json                  # Canonical GCP WAF pillar registry and skill URLs
│   └── design-system/                    # Corporate Design System Model (Machine-readable)
│       ├── tokens.json                   # Color palettes, typography, spacing, elevations
│       ├── components.json               # Approved UI component registry
│       └── a11y-rules.json               # WCAG 2.1 AA accessibility constraints
├── scripts/                              # Deterministic mechanical tools (Python 3.12+)
│   ├── check_boundaries.py               # Boundary evaluation engine
│   ├── hook_boundary_guard.py            # PreToolUse hook adapter (reads stdin JSON, returns allow/deny)
│   ├── validate_contract.py              # OpenAPI 3.x / JSON schema / SPEC.md validator
│   ├── validate_adrs.py                  # MADR compliance & Gate 0.5 Human Approval Token validator
│   ├── audit_waf_compliance.py           # Evaluates architecture against GCP WAF taxonomy
│   ├── audit_implementation.py           # AST-based 1-class-per-file & domain purity auditor
│   ├── audit_test_coverage.py            # OpenAPI status code & PRD User Story coverage auditor
│   ├── validate_ui_spec.py               # UXP token, component whitelist, and WCAG auditor
│   └── run_gate_suite.sh                 # Master hard gate orchestrator (ruff, mypy, pytest, mutmut, bandit)
├── archetypes/
│   └── python-clean-arch/                # Python Reference Stack Governance Pack (plugin-internal, hidden from end users)
│       ├── archetype.json                # Tooling manifest & execution commands
│       ├── conventions/
│       │   ├── code-layout.md            # Clean Architecture layout standard
│       │   └── code-layout.env           # Machine-readable paths for hooks
│       ├── guidelines.md                 # 1-class-per-file, Google docstrings, typing, pure domain
│       ├── config/
│       │   └── pyproject.toml            # Strict central configs (Ruff D/ANN, Mypy strict, Pytest 100%)
│       └── templates/
│           ├── patterns/                 # 5 hidden pattern BLUEPRINTS (reference only; never copied into user repo)
│           │   ├── decision-list/        # Rule(abc.ABC) + engine.py dispatcher
│           │   ├── repository-service/   # Repository(abc.ABC) + service.py (+ in-memory adapter)
│           │   ├── state-machine/        # State/Event/TransitionTable + state_machine.py
│           │   ├── pipeline-reducer/     # PipelineStage(abc.ABC) + pipeline.py runner
│           │   └── algorithmic-core/     # Solver(abc.ABC) + solver_engine.py
│           ├── entrypoints/
│           │   └── app.py                # Minimal FastAPI service adapter
│           ├── tests/                    # Unit & contract test templates
│           └── deploy/
│               ├── Dockerfile            # Multi-stage distroless Python container
│               └── cloudbuild.yaml       # GCP Cloud Build CI/CD pipeline
└── skills/
    ├── conduct/                          # Master Conductor (6-phase state machine & budget management)
    ├── prd-validate/                     # Intake Gatekeeper & WAF Gap Assessment (Audits & Clarifies PRD.md)
    ├── architect-design/                 # Lead Architect Persona (Tier-1 Macro-Decomposition, GCP WAF & ADRs)
    ├── secops-audit/                     # Security Architect Persona (STRIDE threat modeling, IAM least-privilege)
    ├── lead-decompose/                   # Subsystem Tech Lead Persona (Tier-2 Micro-Decomposition, Contract Freezing)
    ├── test-architect/                   # Independent Test Architect Persona (Orthogonal Behavioral Test Generation)
    ├── code-implement/                   # Specialist Implementer Persona (Strict TDD Red-Green-Refactor)
    ├── gate-enforcer/                    # Gatekeeper Persona (Mechanical hard gate runner & remediation assistant)
    ├── sre-deploy/                       # Release & SRE Persona (Cloud Run, Terraform IaC, Smoke Tests)
    └── ux-design/                        # UXP / Frontend Architect Persona (Phase 5: UI/UX & Design Systems)
```

---

## The Core Thesis: Unbypassable Triggers vs. Ungameable Verdicts

A deterministic gate script that exits `1` on failure produces an **ungameable verdict**. However, if the gate is triggered only by prose inside `SKILL.md` (relying on the worker agent to run it voluntarily), the trigger remains **bypassable under task pressure**.

Maestro implements **3 complementary defense-in-depth enforcement layers**:

1. **Layer 1: PreToolUse Hooks (Real-Time Prevention)**
   - Configured in `hooks.json`.
   - The harness intercepts every `write_to_file` and `replace_file_content` tool call before execution.
   - Dispatches payload to `scripts/hook_boundary_guard.py`. Returns `{"decision": "deny"}` immediately if the file path is outside the agent's assigned module boundary.
   - The agent cannot bypass this because execution is blocked by the harness runtime before file writes happen.

2. **Layer 2: Controller & Harness-Driven Phase Gates (Progression Control)**
   - The worker agent **never self-certifies**.
   - Phase progression is owned exclusively by the Master Orchestrator (`/conduct`) or harness Stop hooks.
   - The controller executes `scripts/run_gate_suite.sh` or specific gate validators at phase transitions (Gate 0, Gate 1, Gate 5, Gate 8).
   - If exit code $\ne 0$, transition is hard blocked. The persona does not decide pass/fail; pass/fail is deterministic code.
   - `/gate-enforcer` is strictly a *remediation assistant* that diagnoses failures and orchestrates bounded retries; it has zero discretion to waive a failing gate.

3. **Layer 3: Git Pre-Commit / CI Backstop (Repository Boundary)**
   - Pre-commit hook executes `run_gate_suite.sh` before any commit is finalized.
   - Provides a final mechanical guarantee outside agent runtime memory.

---

## Phase-by-Phase Roadmap

### Phase 1: Mechanical Tooling, Gating Scripts & Unbypassable Triggers (`scripts/` & `hooks.json`)
> **Goal**: Build deterministic, zero-LLM-bias Python scripts that enforce mechanical hard gates and bind unbypassable lifecycle hooks.

- [x] **Task 1.1: Directory Boundary Guard (`scripts/check_boundaries.py` & `scripts/hook_boundary_guard.py`)**
  - Intercepts file write and edit tool calls via `PreToolUse` hook.
  - Verifies that worker subagents only modify files within their assigned subsystem folder (e.g., `src/modules/<subsystem>/`).
  - `hook_boundary_guard.py` reads harness stdin JSON and outputs `{"decision": "allow" | "deny"}`.
  - Unit tests in `tests/test_check_boundaries.py` (100% test coverage, strict mypy, ruff clean).

- [x] **Task 1.2: Contract & Schema Validator (`scripts/validate_contract.py`)**
  - Parses and validates OpenAPI 3.x specifications (`openapi.yaml`) and JSON schemas.
  - Enforces schema completeness: explicit status codes (`200`/`201`, `400`, `422`, `500`), typed request/response models, and versioned paths.
  - Unit tests in `tests/test_validate_contract.py` (100% test coverage, strict mypy, ruff clean).

- [x] **Task 1.3: GCP Well-Architected Framework Auditor (`scripts/audit_waf_compliance.py`)**
  - Ingests `architecture.md` and evaluates it against the 7 GCP WAF pillars using `resources/waf/gcp_waf.json`.
  - Verifies that all 7 pillars are addressed in dedicated sections citing official `cloud.google.com/architecture/framework/...` reference links.
  - Confirms that PRD NFRs (Cost, Reliability, Security, Ops, Perf, Scale, Sustainability) are mapped to concrete GCP services in a frozen decisions table.
  - Unit tests in `tests/test_audit_waf.py` (100% test coverage, strict mypy, ruff clean).

- [x] **Task 1.4: Architecture Decision Record (ADR) & HITL Validator (`scripts/validate_adrs.py`)**
  - Enforces MADR structural compliance for all `docs/adr/XXXX-*.md` files.
  - Checks monotonic sequence numbering, required MADR sections, and Status $\in$ `{proposed, accepted, superseded}`.
  - Checks that every entry in `architecture.md`'s *Frozen Cloud Service Decisions* table traces to an `accepted` ADR.
  - Verifies the **Human Approval Token** (`Approved-by: <identity>`) in Gate 0.5 before unlocking Gate 1.
  - Unit tests in `tests/test_validate_adrs.py` (100% test coverage, strict mypy, ruff clean).

- [x] **Task 1.5: Master Gate Suite Runner (`scripts/run_gate_suite.sh`)**
  - Orchestrates the full gate sequence deterministically:
    1. `ruff check src/` (Linting)
    2. `ruff format --check src/` (Formatting)
    3. `mypy --strict src/` (Static Type Safety)
    4. `python3 scripts/audit_implementation.py src/modules/<subsystem>` (Gate 2: 1-class-per-file, domain purity, docstrings)
    5. `pytest --cov=src --cov-fail-under=100` (100% Branch & Statement Coverage)
    6. `bandit -r src/` + `pip-audit` (SAST & Vulnerability Scanning)
    7. `pytest tests/contract/ tests/behavioral/` (Orthogonal Contract & Behavioral Verification)
    8. `python3 scripts/audit_test_coverage.py src/modules/<subsystem>/openapi.yaml` (Gate 8: status-code & User-Story coverage)
  - Returns exit code `0` on total pass, or diagnostic JSON on failure.

- [x] **Task 1.6: Role-Scoped Boundary & PreToolUse Enforcement (`scripts/check_boundaries.py` & `scripts/hook_boundary_guard.py`)**
  - Enforces role isolation based on `MAESTRO_ACTIVE_ROLE`:
    - `test-author`: Allowed only `tests/contract/<subsystem>/` and `tests/behavioral/<subsystem>/`.
    - `implementer`: Allowed only `src/modules/<subsystem>/`, `tests/unit/<subsystem>/`, and `tests/integration/<subsystem>/` (strictly denied from touching contract/behavioral tests).
    - Unset / `any`: Allows all subsystem paths for backward compatibility.
    - Unknown role: Fails closed (denies all writes).
  - PreToolUse hook intercepts tool calls and enforces role boundaries at runtime.
  - Unit and mutation tests in `tests/test_check_boundaries.py` and `tests/test_hook_boundary_guard.py`.

- [x] **Task 1.7: Cryptographic RED-Lock Verification (`scripts/verify_red_suite.py`)**
  - `lock`: Asserts orthogonal test suite genuinely fails against unimplemented code (exits `1` if green), writes `.maestro/red_lock/<subsystem>.json` with SHA256 hashes of test files.
  - `check`: Verifies manifest exists and ensures zero test files have been modified, added, or deleted during developer implementation.
  - Unit and mutation tests in `tests/test_verify_red_suite.py`.

- [x] **Task 1.8: Structured Adversarial Architecture Review Validator (`scripts/validate_adversarial_review.py`)**
  - Enforces the Elephant-Goldfish architecture review protocol before Gate 0.5 HITL sign-off.
  - Validates 3 critic objection sets in `docs/adr/objections/<resilience|cost|simplicity>.json`.
  - Verifies structured objections, non-placeholder claims, and valid challenged ADR references.
  - Requires `docs/adr/objections/resolutions.json` mapping 100% of objections to valid dispositions (`mitigated`, `accepted-risk`, `rejected`) and non-placeholder resolutions.
  - Unit and mutation tests in `tests/test_validate_adversarial_review.py`.

---

### Phase 2: Python Reference Stack Archetype (`archetypes/python-clean-arch/`)
> **Goal**: Create the pluggable Python 3.12+/3.13 governance pack enforcing clean architecture, strict TDD, and Google-style documentation.

- [x] **Task 2.1: Archetype Manifest (`archetypes/python-clean-arch/archetype.json`)**
  - Defines execution commands, runtime requirements (Python 3.12+), linter commands, and coverage thresholds.

- [x] **Task 2.2: Conventions & Guidelines**
  - `conventions/code-layout.md` & `code-layout.env`: Package structure (`src/domain/`, `src/adapters/`, `src/entrypoints/`, `tests/unit/`, `tests/engine/`, `tests/contract/`).
  - `guidelines.md`: Explicit standards:
    - Exactly **one public class per file**.
    - **100% Google-style docstrings** for module, class, methods, and attributes.
    - **Frozen dataclasses / Pydantic V2** for domain models.
    - **Pure domain core** with I/O and datastores isolated in `adapters/`.
    - Support for all **5 Maestro Domain Patterns** (Decision-List, Repository-Service, State-Machine, Pipeline-Reducer, Algorithmic-Core).

- [x] **Task 2.3: Central Configuration Manifests (`config/pyproject.toml`)**
  - Strict Ruff configuration (`select = ["E", "F", "I", "D", "ANN"]`, `pydocstyle.convention = "google"`).
  - Strict Mypy configuration (`disallow_untyped_defs = true`, `strict = true`).
  - Strict Pytest configuration (`--cov-report=term-missing`, `--cov-fail-under=100`).

- [x] **Task 2.4: Domain Pattern Templates (`templates/patterns/`)**
  - `decision-list/`: Generic `Rule(abc.ABC)` base class + `engine.py` dispatcher skeleton.
  - `repository-service/`: `Repository(abc.ABC)` interface + `service.py` skeleton.
  - `state-machine/`: `State`, `Event`, `TransitionTable`, and `state_machine.py` skeleton.
  - `pipeline-reducer/`: `PipelineStage(abc.ABC)` base class + `pipeline.py` runner skeleton.
  - `algorithmic-core/`: `Solver(abc.ABC)` / `Strategy(abc.ABC)` algorithm skeleton.
  - `entrypoints/app.py`: Minimal FastAPI service adapter.
  - `tests/test_unit_template.py` & `tests/test_contract_template.py`: Unit and contract test boilerplate.
  - `deploy/Dockerfile` & `deploy/cloudbuild.yaml`: Multi-stage Python Cloud Run deployment assets.

- [x] **Task 2.5: Wire `/code-implement` to consume the selected blueprint (Pattern Generation Model)**
  > **Install-and-use principle**: end users never see or copy pattern files. The archetype ships hidden inside the installed plugin, and Maestro *generates* finished code from a hidden blueprint + a per-project spec. Three artifacts, only one of which lands in the target repo:
  1. **Blueprint** — `archetypes/python-clean-arch/templates/patterns/<pattern>/` (static, shared, plugin-internal; never copied out).
  2. **Spec** — `src/modules/<subsystem>/SPEC.md` (per subsystem; `/lead-decompose` already records the selected `pattern:` — see Task 3.4).
  3. **Generated code** — `src/modules/<subsystem>/domain/…` synthesized by `/code-implement` from the blueprint (shape) + `SPEC.md` (domain specifics).
  - The Implementer reproduces the invariant machinery from the blueprint and generates only the domain-specific content (e.g. the real state-transition table) from the spec — the customer's business logic is generated, never pre-bundled.
  - **Never** copy `archetypes/` into the target repo; only generated `src/modules/` code is delivered to the user.

---

### Phase 3: Clean-Context Persona Skills (`skills/`)
> **Goal**: Implement the specialized persona skills with rigid prompt templates and clean context boundaries.

- [x] **Task 3.1: Product Intake & WAF Gap Assessment Skill (`skills/prd-validate/SKILL.md`)**
  - Ingests draft PRD or requirement prompt.
  - Dynamically fetches live **Workload Assessment Questions** from Google's official `google-cloud-waf-*` skills referenced in `resources/waf/gcp_waf.json`.
  - Performs **WAF-Driven Intake Assessment** across all GCP WAF pillars.
  - Freezes validated, unambiguous `PRD.md` as the authoritative source of truth.

- [x] **Task 3.2: Lead Cloud Architect Skill (`skills/architect-design/SKILL.md`)**
  - Ingests frozen `PRD.md`, fetches live **Validation Checklists** from Google's WAF skills in `resources/waf/gcp_waf.json`.
  - Performs Tier-1 Macro-Decomposition, authors MADRs in `docs/adr/`, produces `architecture.md`, and runs `audit_waf_compliance.py` and `validate_adrs.py`.

- [x] **Task 3.3: Security Architect Skill (`skills/secops-audit/SKILL.md`)**
  - Audits architecture for STRIDE threats, IAM least privilege, and secret isolation.
  - Generates `docs/security.md` containing trust boundary diagrams, STRIDE threat matrices, IAM least-privilege matrices, and Secret Manager/KMS policies.
  - Bundles mechanical validator `scripts/audit_security.py` (100% test coverage) enforcing structural invariants, all 6 STRIDE categories, and PRD Security NFR traceability.
  - Bundles reference guides (`references/stride-threat-matrix.md`, `references/iam-least-privilege.md`, `references/secret-management-standards.md`, `references/security-template.md`).
  - Includes 20-query trigger evaluation suite in `evals/trigger_evals.json`.

- [x] **Task 3.4: Subsystem Tech Lead Skill (`skills/lead-decompose/SKILL.md`)**
  - Enforces modular monolith default, performs Tier-2 micro-decomposition, authors and freezes `openapi.yaml` and schemas.
  - Classifies subsystem computational shape and selects matching pattern from the **5 Domain Patterns Catalog**.

- [x] **Task 3.5: Independent Test Architect Skill (`skills/test-architect/SKILL.md`)**
  - Orthogonal Verifier: Derives behavioral contract tests strictly from `PRD.md` and `openapi.yaml`.
  - Mechanical Gate 8 enforcement via `scripts/audit_test_coverage.py`.

- [x] **Task 3.6: Specialist Implementer Skill (`skills/code-implement/SKILL.md`)**
  - Implements assigned rule/module using **strict TDD Red-Green-Refactor loop**.
  - Enforces Single Responsibility (1 class per file), 100% unit test coverage, `mypy --strict`, Google-style docstrings, and strict boundary isolation via `scripts/check_boundaries.py`.

- [x] **Task 3.7: Gatekeeper & Remediation Engine (`scripts/gate_controller.py` & `scripts/run_gate_suite.sh`)**
  - Consolidated into the mechanical Gate Controller (`scripts/gate_controller.py`): tracks execution state in `.maestro/gate_state.json`, enforces phase interlocks, and strictly limits remediation to 3 attempts (tripping the circuit breaker on attempt 4 with exit code 3). Zero LLM discretion to waive gates.

- [x] **Task 3.8: Release Engineering & Deployment Scaffolding (Conductor Phase 5)**
  - Folded into Master Conductor (`/conduct`) Phase 5: scaffolds multi-stage Cloud Run `Dockerfile`, `cloudbuild.yaml`, and container smoke-test scripts.

- [x] **Task 3.9: Master Conductor Skill (`skills/conduct/SKILL.md`)**
  - Deterministic 6-phase state machine coordinating Phases 0 through 6, clean context boundaries, subagent dispatch templates, mandatory Gate 0.5 HITL checkpoints, and bounded 3-attempt remediation loops.
  - Bundles reference guides (`references/orchestration-state-machine.md`, `references/subagent-dispatch-templates.md`).
  - Includes 20-query trigger evaluation suite in `evals/trigger_evals.json`.

---

### Phase 4: Plugin Manifest, Lifecycle Hooks & End-to-End Validation
> **Goal**: Assemble `plugin.json`, bind hooks in `hooks.json`, and execute an automated dry-run against a reference PRD.

- [x] **Task 4.1: Plugin Manifest & Hook Bindings (`plugin.json` & `hooks.json`)**
  - Configured `plugin.json` manifest with plugin metadata.
  - Bound `hook_boundary_guard.py` as an active `PreToolUse` hook in `hooks.json` for all file-modifying tools.

- [x] **Task 4.2: Automated Plugin Test Suite (`tests/`)**
  - 251 unit and integration tests across `tests/` verifying gate pass/fail conditions, boundary guards, RED-lock manifests, adversarial review validation, and controller circuit breakers (100.00% statement and branch coverage).

- [ ] **Task 4.3: End-to-End Vertical Slice Spine Run**
  - Run `/conduct` through the full gate sequence on a minimal subsystem (`redirect_resolver`).
  - Verify that all generated Python code passes 100% Ruff, 100% Mypy, 100% Pytest coverage, and produces valid GCP Cloud Run deployment artifacts.

---

### Phase 5: UXP / Frontend Architecture Track & Corporate Model Validation
> **Goal**: Introduce the orthogonal User Experience Platform (UXP) persona, machine-readable corporate design models, and mechanical UI specification gates.

- [ ] **Task 5.1: Corporate Design System Models (`resources/design-system/`)**
  - `tokens.json`: Canonical machine-readable design tokens (color palette, spacing scale, typography, elevations, breakpoints).
  - `components.json`: Whitelisted corporate UI component registry (atoms, molecules, layout containers) with allowed variants and props.
  - `a11y-rules.json`: WCAG 2.1 AA compliance constraints (minimum contrast ratios 4.5:1 text / 3.0:1 UI, mandatory aria labels, keyboard focus traps).

- [ ] **Task 5.2: UXP / Frontend Architect Skill (`skills/ux-design/SKILL.md`)**
  - Ingests user stories and PRD UX requirements.
  - Generates `docs/UI_SPEC.md` containing:
    - Screen inventory and component hierarchy.
    - Wireflows & Finite State Machine (FSM) navigation tables.
    - Token bindings (zero magic hex/px values).
    - Responsive layout breakpoints and interaction states (default, hover, focus, disabled, loading, error).
  - Integrates with Stitch MCP for screen generation and design system synchronization.

- [ ] **Task 5.3: UI Specification & Design System Validator (`scripts/validate_ui_spec.py`)**
  - Deterministic mechanical auditor verifying:
    1. **Zero Magic Values**: Every color, font size, and spacing value in `UI_SPEC.md` strictly resolves to `resources/design-system/tokens.json`.
    2. **Component Registry Whitelist**: All UI elements reference valid components in `resources/design-system/components.json`.
    3. **WCAG Contrast Verification**: Computes relative luminance and verifies contrast ratios meet `a11y-rules.json`.
    4. **Navigation State Machine Completeness**: Verifies all screen transitions have explicit trigger events and error fallback routes.
  - Unit tests in `tests/test_validate_ui_spec.py` (100% test coverage, strict mypy, ruff clean).

---

## Verification Criteria & Definition of Done

1. **Unbypassable Enforcement**: `PreToolUse` hooks in `hooks.json` mechanically block cross-boundary writes at the runtime harness level.
2. **Deterministic Gate Verdicts**: Every mechanical script in `scripts/` exits `0` on valid code and exits `1` with clear diagnostics on invalid code.
3. **Traceable Decision Freezing**: All architectural decisions in `architecture.md` trace to accepted MADRs validated by `validate_adrs.py`.
4. **Strict TDD Compliance**: Python archetype enforces Red-Green-Refactor and blocks commits without 100% coverage.
5. **Clean Documentation Standard**: Zero lint errors under Ruff `D100-D107` (Google-style docstrings everywhere).
6. **Corporate UI Conformance**: `UI_SPEC.md` strictly validates against `resources/design-system/` without magic styling values.

