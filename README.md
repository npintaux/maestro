# 🎼 Maestro: Autonomous Swarm Orchestrator Plugin

> **Transform a single PRD into a production-grade, tested, and deployable application using a persona-driven subagent swarm, multi-tier architectural decomposition, and mechanical hard gates.**

---

## 🌟 Overview

**Maestro** is an autonomous engineering orchestration plugin built for **Google Antigravity**. (Ports to Gemini CLI and Claude Code are planned; today the subagent-dispatch and plugin-path conventions target Antigravity.) Rather than attempting to build entire systems in a single context window or relying on loose prompts, Maestro functions as an **Autonomous Tech Lead** that:

1. **Ingests your PRD** (Functional + Non-Functional Requirements).
2. **Decomposes the system** across two architectural tiers (Macro-System Topology $\to$ Microservice/Module Boundaries).
3. **Drafts & Freezes Interface Contracts** (`openapi.yaml`, Protobufs, Schemas, or Interface ABCs) audited for PRD traceability.
4. **Binds Pluggable Technology Archetypes** (Python, Go, TypeScript, Rust, etc.) with strict coding and documentation governance.
5. **Spawns an Orthogonal Swarm** of specialized subagents (Developers $\ne$ Testers) operating in isolated contexts.
6. **Enforces Mechanical Hard Gates** (Linters, Typecheckers, 100% Unit Test Coverage via strict TDD, Mutation Adequacy, and SAST) where exit codes $\ne 0$ block delivery.
7. **Generates Cloud Deployment Infrastructure** (Google Cloud Platform / Cloud Run, Terraform, Dockerfiles) ready for production.

---

## 🚀 Quick Start: Single-Prompt Delivery

Once installed in your agent environment, you trigger the entire software delivery pipeline with a single slash command and your PRD:

```bash
/conduct
```

### Example Prompt

```markdown
/conduct

TARGET STACK: Python 3.13 (or Go 1.24 / TypeScript)
TARGET CLOUD: Google Cloud Platform (GCP)

PRD:
Build a high-throughput IoT Device Telemetry Ingestion and Analytics Platform:
- Functional Requirements:
  - Ingest telemetry events (device_id, timestamp, temperature, pressure, battery_level).
  - Deduplicate events and reject out-of-order batches.
  - Query real-time aggregation metrics (avg, p95, min, max) per device group.
- Non-Functional Requirements:
  - Latency: Ingestion response < 50ms p95.
  - Reliability: Graceful backpressure, zero data loss on ingestion surges.
  - Security: JWT-based device authentication, Secret Manager integration, no plaintext secrets.
  - Cost: Serverless auto-scaling to zero when idle.
  - Governance: 100% linter passing, 100% test coverage via TDD, full docstrings on all modules/classes/methods.
```

That's it. Maestro conducts the entire swarm, enforces the gates, and delivers a fully tested, documented application.

---

## 👥 The Persona Skills Catalogue

Maestro equips your environment with 7 clean-context persona skills. Subagents invoke these skills independently to maintain pure focus, while mechanical scripts and lifecycle hooks enforce non-negotiable gates:

| Persona | Skill Name | Responsibility & Clean Context Boundary |
| :--- | :--- | :--- |
| **Master Conductor** | `/conduct` | Coordinates the 6-phase lifecycle, manages agent budget, and triggers phase transitions. |
| **Intake Gatekeeper** | `/prd-validate` | Ingests PRD, performs **WAF-Driven Intake Assessment**, and clarifies missing NFRs before freezing `PRD.md`. |
| **Cloud Architect** | `/architect-design` | Performs Tier-1 Macro-Decomposition; benchmarks architecture against the **GCP Well-Architected Framework (WAF)** and drafts MADRs. |
| **Security Architect** | `/secops-audit` | Conducts STRIDE threat modeling, IAM least-privilege verification, and secret boundary audits. |
| **Subsystem Tech Lead** | `/lead-decompose` | Performs Tier-2 Micro-Decomposition into modules/services and drafts frozen OpenAPI contracts and SPEC.md. |
| **Independent Test Architect** | `/test-architect` | **Orthogonal Verifier**: Derives behavioral and contract test suites directly from the PRD & contracts in a clean context. |
| **Specialist Implementer** | `/code-implement` | Implements business logic in isolated directories using **strict TDD** and pattern blueprints. |

> **Mechanical Gate Enforcement & Remediation**: Gate execution is handled by `scripts/gate_controller.py` (interlocked state machine + strict 3-attempt circuit breaker) rather than an LLM referee, ensuring zero discretion on test, linter, or security failures.

---

## 🧠 Execution Model: Real Subagents, Clean Contexts, Parallel Dispatch

Maestro is a **true multi-agent orchestrator**, not a single agent role-playing personas in one long conversation. Two properties are load-bearing:

### 1. Every persona runs as a real subagent in an isolated, clean context

When the Conductor (`/conduct`) reaches a phase, it **dispatches** the persona through the host's `invoke_subagent` mechanism (`TypeName: "self"`). The subagent boots with a **fresh context**: it receives only its persona skill, the explicit file paths of its upstream artifacts (the Artifact Ingestion DAG), its target deliverables, and its mechanical verification command — **not** the Conductor's conversation history.

> **This is dispatch, not simulation.** The Conductor does *not* execute persona logic inline, and it does *not* write a persona's artifacts on its behalf. Every artifact (`docs/adr/`, `SPEC.md`, tests, domain code) is produced by a **separately dispatched agent reasoning in its own window**.

Context isolation is what makes the roles meaningful: the **Independent Test Architect** stays genuinely *orthogonal* because implementation code was never in its context, and an adversarial critic can't rubber-stamp a design it shares no context with.

### 2. Independent work is dispatched in parallel

Where phases carry no data dependency, Maestro fans out concurrently instead of serializing — this is most visible when the Conductor dispatches to the Lead / Technical personas:

| Phase | Concurrent dispatch |
| :--- | :--- |
| **Phase 1 — Architecture & Security** | The **Lead Cloud Architect** (`/architect-design`) and **Security Architect** (`/secops-audit`) run in parallel — the security posture doesn't wait on the full topology. |
| **Phase 1 — Adversarial Review** | The 3 architecture critics (`resilience`, `cost`, `simplicity`) are dispatched in a **single concurrent `invoke_subagent` call**, each attacking the draft ADRs from its own lens in its own context. |
| **Phase 2–4 — Per-subsystem** | Each subsystem's **Tech Lead**, **Test Architect**, and **Implementer** are dispatched per module, so independent subsystems progress without blocking one another. |

> **On guarantees:** context isolation and true parallelism are provided by the **host dispatch layer** (Antigravity `invoke_subagent`). Maestro's mechanical gates verify the *artifacts* a subagent produces — structure, completeness, resolution — they do not (and cannot) re-verify from disk that a subagent ran in a separate context. The dispatch instruction is the contract; the gates check its outputs.

---

## 🔌 Pluggable Stack Architecture

Maestro is **100% technology-agnostic**. The core orchestration logic, state machine, and gating mechanisms do not depend on any single language.

Instead, technology stacks are bundled as **Stack Governance Packs** (`archetypes/<stack>/`):

```
archetypes/
├── python-clean-arch/         # Python 3.13: Ruff, Mypy Strict, Pytest 100% Cov, Rule ABCs, Google Docstrings
├── go-clean-arch/             # Go 1.24: Golangci-lint, Table-Driven Tests, Clean Interfaces, Revive
├── ts-node-clean-arch/        # TypeScript: ESLint, TSDoc, Vitest Coverage, Strict Nulls
└── rust-clean-arch/           # Rust: Cargo clippy, Cargo test, Rustdoc
```

Each archetype provides:
1. **`archetype.json`**: Tooling commands (linter, typechecker, test runner, coverage target).
2. **`conventions/code-layout.md` & `.env`**: Deterministic directory placement and file naming rules.
3. **`guidelines.md`**: Language idioms, documentation standards (e.g. one class per file, full docstring rules).
4. **`templates/`**: Base contracts/ABCs, composed engine skeletons, immutable data models, and test boilerplate.
5. **`config/`**: Centralized linter and formatter configs (`pyproject.toml`, `.golangci.yml`, `tsconfig.json`).

---

## 🧩 How Maestro Generates Your Code (Install & Use)

Maestro is **install-and-use**. You never open, copy, or edit a pattern file — the pattern logic ships *hidden inside the plugin*, and Maestro generates finished code for your subsystem. There are three distinct things, and **only one of them ever lands in your repository**:

1. **Blueprints — hidden, shared, static.** Each of the 5 domain patterns has one canonical, gate-passing reference implementation bundled inside the plugin (`archetypes/<stack>/templates/patterns/<pattern>/`). It is identical for every project and is **never copied into your repo**.
2. **Spec — generated per project.** During decomposition, the Tech Lead writes `SPEC.md` declaring the chosen `pattern:` and your domain model — the concrete states, rules, or entities drawn from *your* PRD. This is requirements, not code.
3. **Your code — generated per project.** The Implementer reads the hidden blueprint as its reference and synthesizes finished, 100%-tested code into `src/modules/<subsystem>/`. The reusable machinery comes from the blueprint; the domain specifics come from your spec.

> **Example.** The `state-machine` blueprint knows the *shape* of a finite state machine. For an order-management PRD, Maestro generates a `DRAFT → SUBMITTED → APPROVED → FULFILLED` transition table; for a booking PRD, a completely different table — both from the same hidden blueprint. You describe the workflow; Maestro writes the code.

**Extending Maestro** (adding a 6th pattern or a new stack pack) is a *plugin-author* task documented in this repository — not something end users ever need to touch.

---

## 🛡️ The Hard Gate Protocol

Under cognitive task pressure, LLM subagents ignore prose instructions. **Maestro enforces non-negotiables as mechanical blocking gates via `scripts/gate_controller.py`:**

```
[PRD Intake]            ──► [docs/PRD.md Validated]
                                │
                                ▼
[Macro Architecture]    ──► [Gate 0: ADR Structural & Sequence Validation]
                        ──► [Gate 1: GCP WAF Compliance Audit]
                        ──► [Gate Security: STRIDE & IAM Policy Audit]
                        ──► [Gate Adversarial: 3-Lens Architecture Critic & Resolutions]
                                │
                                ▼
[Human-In-The-Loop]     ──► [Gate 0.5: Mandatory ADR Sign-Off Token]
                                │
                                ▼
[Micro Decomposition]   ──► [Gate 2: OpenAPI 3.x Contract & SPEC.md Traceability]
                                │
                                ▼
[Orthogonal Tests]      ──► [tests/contract/ & tests/behavioral/ Generated (test-author role)]
                        ──► [RED-Lock: Cryptographic Suite Lock before Implementation]
                                │
                                ▼
[TDD Implementation]    ──► [PreToolUse Hook: Role & Directory Boundary Guard (implementer role)]
                        ──► [Gate 3: Ruff Linter + Mypy Strict + 1-Class-per-File Audit]
                        ──► [Gate 4: RED-Lock Check + 100% Pytest Coverage + Endpoint Audit + Pip-Audit]
                                │
                                ▼
[Release Engineering]   ──► [Dockerfile + Cloud Build CI Scaffolding]
```

If any gate fails (Exit Code $\ne 0$), the diagnostic is captured by `scripts/gate_controller.py` with a **bounded remediation budget** (max 3 attempts). Exceeding 3 attempts trips the circuit breaker (`exit 3`) and hard-halts execution.

---

## 🗺️ Future Roadmap: Git Worktrees & Autonomous PR Lifecycle

To support team-scale concurrency and true enterprise Git workflows, future versions of Maestro will introduce:

* **Git Worktree Isolation**: Each module subagent operates in a dedicated, isolated `git worktree` (`git worktree add ../feature-module-x`).
* **Autonomous Branch & PR Lifecycle**:
  * Implementer subagents commit against issue branches with conventional commits.
  * Subagents open Pull Requests (PRs) targeting `main`.
  * The Gatekeeper and Security Architect subagents review and approve PRs via MCP GitHub integrations.
  * Autonomous merge conflict resolution and upstream rebasing.
* **Multi-Repo Federation**: Orchestrating cross-repository contracts across microservice fleets.

---

## 📄 License

Apache 2.0. Built for the agentic engineering community.
