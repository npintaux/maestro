# Maestro Orchestration State Machine & Gate Verification Matrix

This reference documents the deterministic 6-phase state machine, gate sequence, input/output artifacts, and mechanical exit conditions enforced by `/conduct`.

---

## 1. Phase State Machine & Gate Sequence

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 0: Product Intake & Requirements Gate                                      │
│ Subagent: /prd-validate                                                          │
│ Output: docs/PRD.md                                                              │
│ Gate -1: Deterministic structural & WAF requirement completeness                 │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 1: Macro-Architecture, ADRs & Security Posture                             │
│ Subagents: /architect-design, /secops-audit, & 3 Critic Subagents                │
│ Outputs: docs/adr/XXXX-*.md, docs/architecture.md, docs/security.md              │
│ Critics: docs/adr/objections/<resilience|cost|simplicity>.json, resolutions.json │
│ Gate 0:   uv run python3 scripts/gate_controller.py run gate-0                   │
│ Gate WAF: uv run python3 scripts/gate_controller.py run gate-1                   │
│ Gate Sec: uv run python3 scripts/gate_controller.py run gate-security            │
│ Gate Adv: uv run python3 scripts/gate_controller.py run gate-adversarial         │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Gate 0.5: Human-In-The-Loop Architectural Sign-Off (MANDATORY CHECKPOINT)        │
│ Action: User reviews docs/adr/ and assigns 'Approved-by: <handle>'               │
│ Gate 0.5: uv run python3 scripts/gate_controller.py run gate-0.5                 │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 2: Subsystem Micro-Decomposition & Contract Gate                           │
│ Subagent: /lead-decompose (per subsystem)                                        │
│ Outputs: src/modules/<subsystem>/openapi.yaml, src/modules/<subsystem>/SPEC.md    │
│ Gate 2:  uv run python3 scripts/gate_controller.py run gate-2 --subsystem …      │
│ Optional UI track (subsystems with a UI only, parallel to Gate 2):               │
│   Subagent: /ux-design → src/modules/<subsystem>/ui-spec.json                     │
│   Gate UI:  uv run python3 scripts/gate_controller.py run gate-ui --subsystem …  │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 3: Orthogonal Behavioral & Contract Test Generation & RED-Lock             │
│ Subagent: /test-architect (per subsystem with MAESTRO_ACTIVE_ROLE=test-author)   │
│ Outputs: tests/contract/<subsystem>/..., tests/behavioral/<subsystem>/...        │
│ RED-Lock: uv run python3 scripts/verify_red_suite.py lock --subsystem <subsystem>│
│ Invariant: Derived strictly from PRD.md + openapi.yaml (isolated from domain)   │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 4: Clean-Architecture TDD Implementation & Quality Gate                    │
│ Subagent: /code-implement (per subsystem with MAESTRO_ACTIVE_ROLE=implementer)   │
│ Outputs: src/modules/<subsystem>/domain/, adapters/, entrypoints/, unit tests    │
│ Gate Suite: uv run python3 scripts/gate_controller.py run gate-3/gate-4        │
│ RED-Lock: Gate 4 verifies verify_red_suite.py check --subsystem <subsystem>     │
│ Optional UI track (subsystems with a frozen ui-spec.json only):                  │
│   Subagent: /frontend-implement (MAESTRO_ACTIVE_ROLE=implementer)                │
│   Outputs: src/modules/<subsystem>/frontend/ (Flask app, templates, tokens.css) │
│   Gate FE: uv run python3 scripts/gate_controller.py run gate-frontend --subsystem … │
│ Remediation: Bounded 3-attempt mechanical loop on failure ($? != 0)              │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 5: Release Engineering & Deployment Scaffolding                            │
│ Role: Release Engineering (Cloud Run Dockerfile & Cloud Build CI Scaffolding)   │
│ Outputs: deploy/Dockerfile, deploy/cloudbuild.yaml, local container smoke tests  │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Phase 6: Delivery & Master Audit Record                                          │
│ Action: Emits final Gate Certification Summary and artifact traceability table  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Gate Verification Matrix

| Gate | Name | Command / Tool | Input Artifacts | Exit Criteria |
|---|---|---|---|---|
| **Gate -1** | PRD Validation | `/prd-validate` checks | User prompt / Draft PRD | `docs/PRD.md` frozen, all 7 WAF NFRs populated, 0 placeholders |
| **Gate 0** | ADR Structural Validity | `uv run python3 scripts/gate_controller.py run gate-0` | `docs/adr/XXXX-*.md` | All MADRs valid format, monotonic IDs, valid status enum |
| **Gate Adv** | Adversarial Architecture Review | `uv run python3 scripts/gate_controller.py run gate-adversarial` | `docs/adr/objections/` | 3 required critic files exist, all objections non-empty, 100% resolved in `resolutions.json` |
| **Gate 0.5** | HITL ADR Approval | `uv run python3 scripts/gate_controller.py run gate-0.5` | `docs/adr/XXXX-*.md` | Every accepted ADR contains `Approved-by: <non-empty>`, `gate-adversarial` passed |
| **Gate 1** | GCP WAF Compliance | `uv run python3 scripts/gate_controller.py run gate-1` | `docs/architecture.md` | All 7 WAF pillars addressed, official URLs cited, decisions table complete |
| **Gate Sec** | Security & STRIDE Posture | `uv run python3 scripts/gate_controller.py run gate-security` | `docs/security.md` | All 6 STRIDE categories, IAM least-privilege matrix, secret inventory, PRD NFR links |
| **Gate 2** | Subsystem Contract & Spec | `uv run python3 scripts/gate_controller.py run gate-2 --subsystem <name>` | `openapi.yaml`, `SPEC.md` | OpenAPI 3.x valid, versioned paths, 2xx/4xx/5xx responses, pattern declared in SPEC |
| **Gate UI** | Frozen UI Contract *(optional — UI subsystems only)* | `uv run python3 scripts/gate_controller.py run gate-ui --subsystem <name>` | `ui-spec.json`, design system | Zero magic values (token-only), whitelisted components, WCAG AA contrast, complete/reachable nav FSM, ≥1 PRD User Story per screen |
| **Gate FE** | Front-End Conformance *(optional — subsystems with a `frontend/` only)* | `uv run python3 scripts/gate_controller.py run gate-frontend --subsystem <name>` | `src/modules/<name>/frontend/`, `ui-spec.json`, design system | `tokens.css` byte-matches generated tokens, zero magic colors in CSS, screen↔template bijection, every transition wired via `url_for` |
| **RED-Lock** | Orthogonal Test Lock | `uv run python3 scripts/verify_red_suite.py lock --subsystem <name>` | `tests/contract/`, `tests/behavioral/` | Test suite genuinely fails against unimplemented code (exit $\ne 0$), SHA256 manifest recorded |
| **Gate 3** | Code Quality & Architecture | `uv run python3 scripts/gate_controller.py run gate-3 --subsystem <name>` | `src/modules/<subsystem>/` | `ruff` clean, `mypy --strict` clean, `audit_implementation.py` clean (1 class/file, Google docstrings) |
| **Gate 4** | Test & Coverage Gates | `uv run python3 scripts/gate_controller.py run gate-4 --subsystem <name>` | `tests/`, `src/` | RED-lock verified untampered, 100% pytest statement coverage (`--cov=src --cov-fail-under=100`), `audit_test_coverage.py` complete |

---

## 3. Human-in-the-Loop (HITL) Checkpoint Rules

1. **Gate 0.5 is a Non-Bypassable Blocker**:
   - The orchestrator **must not** invoke `/lead-decompose` or scaffold subsystem code until the human user explicitly approves the ADRs.
   - When presenting Gate 0.5 to the user, display a concise summary of all proposed ADRs and the exact file links.
   - Prompt format: *"Please review the architectural decisions in `docs/adr/`. If approved, reply with 'Approve ADRs' or assign your handle to `Approved-by:` in the ADR files."*
2. **Re-approval on Architectural Changes**:
   - If a subsequent phase requires changing an accepted ADR, a new superseding ADR must be created (`XXXX-<slug>.md` with `* **Superseded by**: ...`), and Gate 0.5 must be re-run for that decision.

---

## 4. Remediation Loop Rules (Max 3 Attempts via gate_controller.py)

When `scripts/gate_controller.py run <stage>` exits with code `1`:
1. **Mechanical State & Attempt Counter**:
   - The controller automatically logs and tracks attempt counts in `.maestro/gate_state.json`.
   - Attempt 1 (Exit code 1): Capture JSON diagnostics $\to$ dispatch targeted repair task to `/code-implement` $\to$ re-run gate.
   - Attempt 2 (Exit code 1): Isolate delta $\to$ dispatch focused repair task to `/code-implement` $\to$ re-run gate.
   - Attempt 3 (Exit code 1): Dispatch final repair task $\to$ re-run gate.
   - Attempt 4 (Exit code 3 - CIRCUIT_BREAKER_TRIPPED): Controller halts execution automatically. Emit escalation report to human user detailing exact failure trace and files modified.
2. **Zero Override Authority**:
   - Progression is mechanically impossible when the circuit breaker is tripped or prerequisite gates have not exited `0`.

---

## 5. Version-Control Transition Matrix

Every gate-pass transition also fires a **git action**, run by a Maestro script that refuses on
violation. GitHub is reached via the `gh` CLI. Branch topology is owned by `scripts/hook_git_gate.py`:
`main`/`master` are protected; `maestro/<prd-slug>` is the per-run integration branch; each
subsystem lives on `issue/<n>-<slug>` in a worktree under `.maestro/worktrees/<subsystem>/`.

| Transition (gate pass) | Git action | Script / command |
|---|---|---|
| `/conduct` start | env preflight; cut integration branch from `main` | `preflight.py`; `git switch -c maestro/<slug> main` |
| Phase 0 → Gate 0 (PRD frozen) | commit PRD; sync `type:story` issues | `commit_artifacts.py prd`; `prd_backlog_sync.py` |
| Phase 1 → Gate 0.5 (arch frozen, HITL) | commit ADRs/arch/security/traceability; gate matrix; create `type:subsystem` issues | `commit_artifacts.py architecture`; `audit_traceability.py`; `create_subsystem_issues.py` |
| Phase 2 → Gate 2 (per subsystem) | commit `SPEC.md` + `openapi.yaml` on integration | `commit_artifacts.py spec --subsystem <name> --issue <n>` |
| Phase 2 → Gate UI (per UI subsystem, optional) | freeze `ui-spec.json` on integration | `commit_artifacts.py ui-spec --subsystem <name> --issue <n>` |
| Phase 3 RED-lock (per subsystem) | lock the suite, then freeze it on integration | `verify_red_suite.py lock …`; `commit_artifacts.py tests --subsystem <name>` |
| Phase 3 → Phase 4 boundary | cut one worktree per subsystem (after all locked) | `worktree_manager.py create --integration maestro/<slug> --spec <spec.json>` |
| Phase 4 (per subsystem, green) | open + machine-merge subsystem PR → integration (proof auto-includes `gate-frontend` when `frontend/` exists) | `ship_pr.py subsystem --integration maestro/<slug>` |
| End of run | open `integration → main` PR (human merges); teardown worktrees | `ship_pr.py integration …`; `worktree_manager.py teardown` |

**Ordering invariants:** (1) **numbers before branches** — subsystem issues exist before any
`issue/<n>-<slug>` branch; (2) **lock before parallel** — every RED suite is locked *and committed*
on integration before worktrees are cut, so each worktree inherits the identical oracle;
(3) **machine-merge on green, human-merge to `main`** — subsystem PRs are squash-merged by the
script only on a fresh green proof; the consolidated integration PR is opened and left for the human.
See `docs/version-control-plan.md` §4–§5 for the full rationale.

