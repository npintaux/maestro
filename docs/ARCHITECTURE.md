# Maestro Architecture (as-built)

The static, structural reference for how Maestro is put together today: its components, the
enforcement model that makes its gates real, the gate catalog, the artifact/data model, and who
owns which document. This is the **structural** companion to two other docs — read those for flow
and rationale:

- [`docs/WORKFLOW.md`](WORKFLOW.md) — the **operational** end-to-end run (phase by phase, the git
  actions, how each subagent works with git).
- [`docs/version-control-plan.md`](version-control-plan.md) — the **rationale** behind the
  version-control spine (why the two-axis issue model, integration branch, and merge policy are
  shaped the way they are).

> This file supersedes the earlier `ARCHITECTURE_PLAN.md` / `IMPLEMENTATION_PLAN.md` (both
> forward-looking planning records, removed once implementation caught up — git history preserves
> them). Where those mixed aspiration with as-built, this describes only what ships in the repo.

---

## 1. Founding thesis

**Under task pressure, an LLM subagent ignores prose instructions.** Every non-negotiable in
Maestro is therefore a *mechanical* artifact — a script that exits non-zero, or a PreToolUse hook
that emits `{"decision":"deny"}` — never a guardrail the model is merely asked to honor. A rule
that is not backed by a hook or an auditor **does not exist**. The whole architecture is a
consequence of taking that sentence literally.

This produces a strict split (Maestro's core distinction):

- **Ungameable verdicts** — deterministic Python auditors in `scripts/` that return exit `1` with
  machine-readable diagnostics whenever code or a spec violates a constraint. Zero LLM discretion.
- **Unbypassable triggers** — mechanisms *outside* subagent discretion that guarantee those
  auditors actually run: PreToolUse hooks (`hooks.json`), the conductor's phase interlocks
  (`gate_controller.py`), and the git-level fences (`hook_git_gate.py`, branch protection on
  `main`).

---

## 2. Repository layout (as-built)

```
/home/user/orchestrated-coding/
├── plugin.json                     # Plugin manifest (name, description) — targets Antigravity
├── hooks.json                      # Two always-on PreToolUse hooks: boundary-guard, git-gate
├── README.md                       # User guide (single-prompt delivery, persona catalogue)
├── resources/
│   └── waf/gcp_waf.json            # Canonical GCP WAF pillar registry + official skill URLs
├── archetypes/
│   └── python-clean-arch/          # The one shipped Stack Governance Pack (see §7)
│       ├── archetype.json          #   tooling commands, coverage threshold
│       ├── conventions/            #   code-layout.md + code-layout.env
│       ├── guidelines.md           #   1-class-per-file, Google docstrings, pure domain
│       ├── config/pyproject.toml   #   strict Ruff (D/ANN) + Mypy strict + Pytest 100%
│       └── templates/
│           ├── patterns/           #   5 hidden pattern BLUEPRINTS (never copied to user repo)
│           ├── entrypoints/        #   minimal FastAPI adapter
│           ├── tests/              #   unit + contract test templates
│           └── deploy/             #   Dockerfile + cloudbuild.yaml
├── scripts/                        # Deterministic mechanical tools (Python 3.12+) — see §4
├── skills/                         # 9 clean-context persona skills — see §3
├── tests/                          # Plugin's own test suite (413 tests, 100% coverage)
└── docs/
    ├── ARCHITECTURE.md             # this file
    ├── WORKFLOW.md                 # operational run
    └── version-control-plan.md     # VCS rationale
```

Artifacts a Maestro *run* generates (`docs/PRD.md`, `docs/adr/`, `docs/architecture.md`,
`docs/security.md`, `docs/traceability.md`, `src/modules/<subsystem>/`, `tests/contract|behavioral|
unit|integration/`, `.maestro/`) live in the **target** repository, not here.

---

## 3. Personas (skills)

Eleven clean-context persona skills. Each runs as a **real dispatched subagent** with a fresh context
(the conductor never executes a persona inline or writes its artifacts for it — see README
"Execution Model"). The `MAESTRO_ACTIVE_ROLE` / `MAESTRO_ACTIVE_SUBSYSTEM` env vars the conductor
sets for each subagent are what the boundary guard reads to fence writes.

| Persona | Skill | Produces | Role / write scope |
|---|---|---|---|
| Master Conductor | `/conduct` | *(orchestration only)* | — runs gates, dispatches subagents |
| Intake Gatekeeper | `/prd-validate` | `docs/PRD.md` (frozen) | root — docs |
| Product Owner | `/prd-to-backlog` | `type:story` GitHub issues | root — docs + `gh` |
| Cloud Architect | `/architect-design` | ADRs, `architecture.md`, `traceability.md` | root — docs |
| Security Architect | `/secops-audit` | `docs/security.md` | root — docs |
| Subsystem Tech Lead | `/lead-decompose` | `openapi.yaml` + **seeds** `SPEC.md` per subsystem | root — docs / contract |
| UX Designer *(optional UI track)* | `/ux-design` | frozen `ui-spec.json` + design system | contract — `src/modules/<sub>/ui-spec.json`, `design-system/` |
| Independent Test Architect | `/test-architect` | contract + behavioral tests | `test-author` — `tests/contract/<sub>/`, `tests/behavioral/<sub>/` |
| Specialist Implementer | `/code-implement` | domain code, unit/integration tests, **maintains** `SPEC.md` | `implementer` — `src/modules/<sub>/`, `tests/unit/<sub>/`, `tests/integration/<sub>/` |
| Front-End Implementer *(optional UI track)* | `/frontend-implement` | Flask/Jinja/CSS front-end built to the frozen `ui-spec.json` | `implementer` — `src/modules/<sub>/frontend/`, `tests/unit/<sub>/`, `tests/integration/<sub>/` |
| Release Manager | `/ship` | PRs; mechanical merge policy | root — `gh` + git (fenced by git-gate) |

The Test Architect / Implementer split is load-bearing: one writes the oracle, the other writes the
code, and the boundary guard makes it **mechanically impossible** for the implementer to edit the
orthogonal tests. See §6.

---

## 4. Mechanical tools (`scripts/`)

Every script follows one house style: a pure, injectable core returning a `@dataclass` report with
`to_dict()`/`is_valid`, a thin CLI (`main(argv)`), `--dry-run` where it mutates state, and exit `1`
with diagnostics on any violation. Each has a matching `tests/test_*.py` at 100% coverage.

**Isolation & hooks**
- `hook_boundary_guard.py` — PreToolUse adapter on file-write tools; reads stdin JSON, delegates to
  `check_boundaries.py`, returns allow/deny. Path-level plane.
- `check_boundaries.py` — the boundary evaluation engine. Role→path policy; **unknown role fails
  closed**.
- `hook_git_gate.py` — PreToolUse adapter on `run_command`; enforces branch topology (no commit/push
  to `main`, only Maestro-shaped branch creation). Branch-level plane. **Fails open** on anything it
  can't confidently evaluate.

**Architecture & governance gates**
- `validate_adrs.py` — MADR structure, monotonic numbering, decision→ADR traceability, and the
  Gate 0.5 `Approved-by:` human-approval token (`--require-approval`).
- `validate_adversarial_review.py` — the Elephant-Goldfish review: 3 critic objection sets
  (resilience/cost/simplicity) + a resolutions file dispositioning 100% of objections.
- `audit_waf_compliance.py` — `architecture.md` vs the 7 GCP WAF pillars in `resources/waf/gcp_waf.json`.
- `audit_security.py` — `security.md` STRIDE matrix, IAM least-privilege, Security-NFR traceability.

**Contract, traceability & implementation gates**
- `validate_contract.py` — OpenAPI 3.x completeness (versioned paths, status codes, error models)
  **and** the sibling `SPEC.md` domain-pattern declaration.
- `audit_traceability.py` — gates `docs/traceability.md` (story↔subsystem matrix) against the PRD and
  architecture; exposes `_parse_matrix` reused downstream so creator and gate can't disagree.
- `audit_implementation.py` — AST-based 1-class-per-file, domain purity, Google-docstring auditor.
- `audit_test_coverage.py` — cross-references the frozen specs against the orthogonal suites
  (documented status codes → contract asserts; **traceability-mapped** User Stories → behavioral
  references; black-box isolation). See §5 for why the story bar comes from traceability, not SPEC.
- `verify_red_suite.py` — `lock` proves the suite fails against absent code and records a SHA256
  manifest; `check` verifies the manifest is present and untampered.
- `validate_ui_spec.py` — validates a subsystem's `ui-spec.json` against the frozen design system in
  `resources/design-system/`: zero magic values (all color/font/size/space resolve to tokens),
  component whitelist, WCAG contrast on token pairs, navigation-FSM completeness, and PRD
  user-story traceability. Backs the `gate-ui` stage (see §5).
- `import_claude_design.py` — **advisory** (not a gate). Unpacks a Claude Design export `.zip` and
  maps the design values it discovers (colors, fonts, component names) against the design system,
  emitting a conformance report (on-brand tokens vs. off-brand magic values) plus an optional draft
  `ui-spec.json` scaffold. It never freezes a contract; `validate_ui_spec.py` remains the authority.
- `validate_frontend.py` — validates a subsystem's *implemented* Flask/Jinja/CSS front-end against
  its frozen `ui-spec.json` + design system: `frontend/static/tokens.css` byte-matches the generated
  token CSS, zero magic colors in any other CSS, a screen↔template bijection, and every declared
  transition wired via `url_for('<target>')`. Also emits the canonical `tokens.css`
  (`--emit-tokens-css`). Backs the `gate-frontend` stage (see §5).

**Gate orchestration**
- `gate_controller.py` — interlocked state machine (`.maestro/gate_state.json`): enforces phase
  dependencies, tracks remediation attempts, and trips a circuit breaker (exit `3`) after 3 failed
  attempts. No LLM can waive it.
- `run_gate_suite.sh` — the actual gate dispatch (stage → commands); driven by `gate_controller.py`.

**Version-control spine** (full flow in [`WORKFLOW.md`](WORKFLOW.md))
- `preflight.py` — refuses to start a run unless cwd is a git worktree, `origin` is HTTPS,
  `gh auth` succeeds, default branch is `main`, and **`main` has branch protection**.
- `commit_artifacts.py` — freezes each artifact set onto the integration branch (idempotent).
- `prd_backlog_sync.py` — reconciles PRD `US-N` sections into `type:story` issues (marker + `src-sha`).
- `create_subsystem_issues.py` — creates one `type:subsystem` issue per subsystem (mints the numbers
  that become branch names); reuses `_parse_matrix`.
- `worktree_manager.py` — cuts one `issue/<n>-<slug>` worktree per subsystem, only from the
  integration branch; idempotent, no-clobber.
- `ship_pr.py` — machine-merges `issue/* → integration` only on a fresh green proof (gate-3 + gate-4
  + RED-lock re-check); opens (never merges) the single `integration → main` PR.

---

## 5. The gate catalog (as-built)

Gate identities and dependencies live in `gate_controller.py` (`PHASE_DEPENDENCIES`); the commands
each runs live in `run_gate_suite.sh`. The dependency DAG is enforced as an interlock — a gate
refuses (exit `2`) if a prerequisite hasn't been recorded as passed.

| Stage | Backing check(s) | Depends on |
|---|---|---|
| `gate-0` | `validate_adrs.py docs/adr` (structure & sequencing) | — |
| `gate-adversarial` | `validate_adversarial_review.py` (3-lens critics + resolutions) | `gate-0` |
| `gate-0.5` | `validate_adrs.py --require-approval` (**HITL** sign-off token) | `gate-adversarial` |
| `gate-1` | `audit_waf_compliance.py docs/architecture.md` | `gate-0.5` |
| `gate-security` | `audit_security.py docs/security.md` | `gate-0.5` |
| `gate-ui` | `validate_ui_spec.py` (token-only, whitelist, WCAG, nav-FSM, US traceability) per UI subsystem — *optional; skipped where no `ui-spec.json`* | `gate-0.5` |
| `gate-frontend` | `validate_frontend.py` (tokens.css sync, zero magic colors, screen↔template bijection, `url_for` nav wiring) per UI subsystem — *optional; skipped where no `frontend/`* | `gate-ui` |
| `gate-2` | `validate_contract.py` (OpenAPI + `SPEC.md` pattern) per subsystem | `gate-1`, `gate-security` |
| `gate-3` | `ruff check` + `ruff format --check` + `mypy --strict` + `audit_implementation.py` | `gate-2` |
| `gate-4` | `verify_red_suite.py check` → `audit_test_coverage.py` → `pytest --cov-fail-under=100` | `gate-3` |
| `boundaries` / `redlock` | standalone helpers (`check_boundaries.py` / `verify_red_suite.py check`) | — |

Two ambient PreToolUse hooks run *continuously*, independent of the staged gates:
`hook_boundary_guard.py` (path plane) and `hook_git_gate.py` (branch plane).

---

## 6. The artifact & data model

Documents flow downstream, each frozen (committed to the integration branch) before the next depends
on it. **Ownership is deliberate** — the axis of who may write each artifact is what makes the gates
meaningful.

```
docs/PRD.md ──────────────┐  (PO-owned, frozen at Gate 0)
                          ├─► type:story issues  (prd_backlog_sync.py)
docs/architecture.md ─────┤
docs/security.md ─────────┤  (architect/secops-owned, frozen at Gate 0.5, HITL)
docs/adr/ ────────────────┘
        │
        └─► docs/traceability.md   (architect-owned; the US-N ↔ subsystem matrix; gated)
                  │
                  ├─► type:subsystem issues  (create_subsystem_issues.py) ─► branch/worktree numbers
                  │
                  └─► the per-subsystem coverage bar consumed by Gate 4  ◄── (see below)

src/modules/<sub>/openapi.yaml   (Tech-Lead-owned, FROZEN at Gate 2 — the interface contract)
src/modules/<sub>/SPEC.md        (Tech-Lead-SEEDED at Gate 2, then IMPLEMENTER-maintained — see §6.1)

tests/contract|behavioral/<sub>/ (Test-Architect-owned; derived from PRD + openapi.yaml; RED-locked)
src/modules/<sub>/ + tests/unit|integration/<sub>/  (Implementer-owned)
```

The **two-axis issue model** (`type:story` from the PRD ⟂ `type:subsystem` from the architecture,
many-to-many via the gated matrix) is detailed in [`WORKFLOW.md`](WORKFLOW.md) §5 and
[`version-control-plan.md`](version-control-plan.md). The **three isolation planes** (path / branch /
git-level) are detailed in [`WORKFLOW.md`](WORKFLOW.md) §4.

### 6.1 SPEC.md ownership — the living-design-doc model

`SPEC.md` is the one artifact whose ownership changes hands, and getting this right is what keeps
the orthogonal-verification guarantee intact:

- **Seeded by the Tech Lead at Gate 2.** `/lead-decompose` writes the initial `SPEC.md` — the
  `> **Selected Domain Pattern**` declaration plus the domain models, error taxonomy, and
  component→User-Story traceability. `validate_contract.py` requires this at Gate 2.
- **Then owned and maintained by the Implementer.** `SPEC.md` sits inside `src/modules/<sub>/`, so
  it is inside the implementer's write boundary. As each issue lands, the implementer updates
  `SPEC.md` to stay in sync with the code it shipped — it is a *living design document*, not a frozen
  artifact. A stale `SPEC.md` is a defect.

Because `SPEC.md` now moves, it **cannot** be the source of any bar the implementer is graded
against, and it **cannot** be what the Test Architect derives the frozen suite from — either would
re-couple the independent oracle to a document the implementer edits. So the frozen behavioral
contract is re-homed to artifacts the implementer does *not* own:

- **The Test Architect derives the orthogonal suite from `docs/PRD.md` (acceptance criteria) +
  `openapi.yaml`** — both frozen upstream — never from `SPEC.md`. A later `SPEC.md` edit thus never
  invalidates a RED-locked suite (this is what closes the Test-Architect↔implementer loop).
- **The Gate 4 coverage bar — "which User Stories must this subsystem satisfy" — is read from the
  architect-owned `docs/traceability.md`**, not from `SPEC.md`. `audit_test_coverage.py` filters the
  matrix by subsystem for the required `US-N` set. If the bar came from `SPEC.md`, an implementer
  could delete a `US-N` line from its own spec to lower its own coverage requirement and still pass.

The Implementer likewise derives *behavior* from the frozen `openapi.yaml` + cited PRD acceptance
criteria (plus its own `SPEC.md` design) — and is told never to read the orthogonal test text as an
implementation source, so the two suites remain a genuine cross-check rather than a tautology.

---

## 7. The pattern-generation model (install-and-use)

Maestro is **install-and-use**: an end user never opens or copies a pattern file. Three artifacts,
only one of which lands in the target repo:

| Artifact | Where it lives | Scope |
|---|---|---|
| **Blueprint** | `archetypes/python-clean-arch/templates/patterns/<pattern>/` (in the plugin) | Static, shared, **never copied out** — carries the *shape* (base ABCs, dispatcher/engine machinery). |
| **Spec** | `src/modules/<sub>/SPEC.md` (generated) | Per project — carries the *domain* (concrete states/rules/entities from the PRD). |
| **Generated code** | `src/modules/<sub>/domain/…` (generated) | Per project — the fused, 100%-tested production code the implementer synthesizes. |

The five domain patterns: **decision-list** (Rule ABC + engine), **repository-service** (Repository
ABC + service), **state-machine** (State/Event/TransitionTable), **pipeline-reducer** (PipelineStage
+ runner), **algorithmic-core** (Solver/Strategy). The Tech Lead selects exactly one primary pattern
per subsystem by the subsystem's dominant computational shape; a second substantial pattern is a
decomposition smell (split the subsystem instead).

Stacks are pluggable via **Stack Governance Packs** (`archetypes/<stack>/`): manifest, conventions,
guidelines, templates, and central tooling config. The orchestration core is stack-agnostic.

---

## 8. What is *not* built yet (roadmap)

To keep this an honest as-built record:

- **Multi-stack archetypes** — only `python-clean-arch` ships. Go / TypeScript / Rust packs are
  illustrated in the README but not present.
- **UXP / frontend track** — *built end-to-end (unwired from live `/conduct`).* Two mechanical gates
  ship: `validate_ui_spec.py` (`gate-ui` — the frozen `ui-spec.json` contract) and
  `validate_frontend.py` (`gate-frontend` — the implemented Flask/Jinja/CSS front-end: tokens.css
  sync, zero magic colors, screen↔template bijection, `url_for` nav wiring), both wired into
  `gate_controller.py` + `run_gate_suite.sh` and optional per subsystem. The corporate-default design
  system (`resources/design-system/`), the thin `ux-design` persona (freezes the contract), the
  advisory `import_claude_design.py` (Claude Design export `.zip` → conformance report + draft
  scaffold), and the `frontend-implement` persona (Flask + Jinja/HTML + CSS, builds to the frozen
  contract) **are** built and unit-tested. Both personas are now **dispatched from `/conduct`'s live
  control flow** — `/ux-design` in the optional Phase 2 UI track (→ `gate-ui` → `commit_artifacts.py
  ui-spec`) and `/frontend-implement` in the optional Phase 4 UI track (→ `gate-frontend`, shipped in
  the subsystem's single PR: `ship_pr.py` auto-appends `gate-frontend` to the proof when
  `src/modules/<sub>/frontend/` exists). Backend-only subsystems skip the whole track. Still pending:
  a **live Stitch MCP call** (specified in the `frontend-implement` persona but not executable here —
  the MCP server is not connected; the gate is the buildable guarantee).
- **SAST / SCA / mutation-adequacy gates** — `bandit`, `pip-audit`, and mutation testing are
  referenced by the Security Architect persona as *advisory* steps but are **not** wired into
  `gate_controller.py`, so they do not mechanically block a merge. Promoting them to blocking
  stages is roadmap work.
- **Multi-repo federation** and **ports to Gemini CLI / Claude Code** — Antigravity-first today.
- **End-to-end vertical-slice run** (`/conduct` all the way through on a real subsystem) — the
  mechanical spine and all gates are built and unit-tested; a full live run is the remaining
  integration milestone.
