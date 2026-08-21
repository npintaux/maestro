# Maestro Version-Control Integration — Implementation Plan

Status: **implemented** — all 9 deliverables in §7 are built, tested, and wired into `/conduct`.
Date: 2026-08-21.

> This document is the **design rationale** (the *why*). For how the finished workflow runs
> end-to-end — the issue model, how each subagent works with git, and how work is reconciled and
> tested together — see [`docs/WORKFLOW.md`](WORKFLOW.md).

This plan wired source control, GitHub issues, branching, and pull requests into the `/conduct`
state machine, **reusing the SDD plugin's skills for workflow shape while re-anchoring every
non-negotiable to a mechanical gate**. (Before it, Maestro built an entire solution without ever
touching git.)

---

## 0. Founding principle (why this looks the way it does)

The SDD skills (`prd-to-backlog`, `commit`, `ship`) enforce their rules in **prose** —
"never commit to `main`" lives in a Guardrails table. Under task pressure, subagents ignore
prose (the Maestro thesis). The only SDD artifact that actually *bites* is
`commit-gate.sh`, a PreToolUse hook that emits `{"decision":"deny"}`.

So the strategy is: **borrow the SDD skills for the workflow's shape, but make each
non-negotiable a script that exits non-zero / denies the tool call.** A version-control
rule that is not backed by a hook or an auditor does not exist.

---

## 1. Prerequisites (documented **and** mechanically enforced)

Maestro operates on an **already-provisioned GitHub repository, cloned locally**. Before
Phase 0, `/conduct` runs `scripts/preflight.py`, which exits non-zero unless **all** hold:

- [ ] cwd is inside a git working tree.
- [ ] an `origin` remote is configured (HTTPS; SSH is out of scope — see `permissioned-github`).
- [ ] `gh auth status` succeeds (the CLI is authenticated).
- [ ] the default branch is `main`.
- [ ] **branch protection exists on `main`.** This is not cosmetic: it is what makes
      "the human owns the merge" real. Without it, that rule is only prose.

Rationale: a precondition that is not a script that bites is not a precondition.

> **Plan availability note.** Branch protection is available for **public** repositories on
> GitHub Free (personal or org). For a **private** repository on a free personal account it is
> **not** available — it requires **GitHub Pro** (or Team/Enterprise for orgs); rulesets are
> gated the same way. So the effective prerequisite is: the target repo is **public**, or the
> account is on **Pro** for a private repo. On a private free-account repo the platform cannot
> enforce the human-merge gate, so `preflight.py` correctly refuses to start — this is honest,
> not a bug. (Verified empirically: a public repo on a free personal account exposes the
> `branches/main/protection` and `rulesets` endpoints; they are not plan-restricted.)

---

## 2. GitHub tooling: `gh` CLI (decision locked)

All GitHub interaction goes through the **`gh` CLI**, per the Antigravity built-in
`permissioned-github` contract:

- Always `gh -R <org>/<repo> …`. No `curl`, no direct GitHub API calls, no scripts against
  the API. Branch ops via `git` over HTTPS.
- Permissions follow the grammar `gh.<action>({...})`, e.g.
  `gh.create({"org":..,"repo":..,"issue":"*"})`, `git.create({"org":..,"repo":..,"branch":"issue/12-..."})`.

> The borrowed `prd-to-backlog` skill assumes the **GitHub MCP server**. That must be
> reworked to `gh` when it is ported into Maestro. (Claude Code compatibility — MCP or a
> different auth path — is deferred; we adapt then.)

---

## 3. The two-axis issue model (the core insight)

Product decomposition and technical decomposition are **orthogonal**, so one cannot be
generated mechanically from the other. There are therefore **two issue layers**:

```
Story issues        US1 ─────┐   ┌───── US2        (type:story,  PO-owned, from PRD)
                             │   │
                          ┌──┴───┴──┐  many-to-many
Subsystem issues   #11 link_store  #12 redirect_resolver  #13 analytics
                   (type:subsystem, engineering-owned)   ← branch = worktree = one unit
                        │
                        └─ #14, #15  (sub-issues a Tech Lead opens under #12)
```

- **Story issues** (`type:story`): vertical slices of user value. Created by the
  `prd-to-backlog` logic (PO persona) from `docs/PRD.md`. A story may touch many subsystems.
- **Subsystem issues** (`type:subsystem`): the technical unit of work. One tracking issue
  per subsystem. **This is the branch/worktree unit** (decision 2a). A subsystem serves many
  stories.
- **Sub-issues**: each Tech Lead subagent may open sub-issues under its subsystem tracking
  issue for its own decomposition (per-endpoint, per-pattern-slice). No new machinery — just
  `gh issue create` scoped to that subsystem.

This respects `prd-to-backlog`'s own responsibility line: *intent is born in GitHub (PO);
its technical form is born in the repo (engineering) and owned there.*

### 3.1 The missing artifact: the story ↔ subsystem traceability matrix

The architect produces `docs/traceability.md` in Phase 1 (the first moment both axes exist):
a table mapping every `US<n>` to the subsystem(s) that realize it.

### 3.2 What creates the subsystem issues, and when

1. Phase 1 (architect) writes `docs/traceability.md` alongside `architecture.md`.
2. At the **Gate 0.5 → Phase 2 handoff** (right after the human approves the architecture),
   a mechanical step reads the matrix and, via `gh`, creates **one `type:subsystem` tracking
   issue per subsystem**, each cross-linking upward to the story issues it serves
   (`Relates to #<story>` / GitHub sub-issue links). This is where subsystem issue **numbers**
   are born — and those numbers feed the branch names `issue/<n>-<subsystem>`, so this step
   MUST precede Phase 3/4.
3. Phase 2 Tech Leads own their subsystem issue and may open sub-issues under it.

### 3.3 The coverage gate (it bites)

`scripts/audit_traceability.py` exits non-zero if the matrix leaves **any story with no
subsystem** (orphaned value) or **any subsystem serving no story** (speculative build). The
many-to-many mapping is a validated artifact, not something a subagent improvises.

---

## 4. Branch topology (per-run integration branch — decision locked)

The no-commit-to-`main` gate is absolute, so RED-lock and all pre-parallel artifacts live on
a **per-run integration branch**:

```
main  ──(protected; human-merge only; agents never push here)
  └─ maestro/<prd-slug>            (per-run integration branch; cut from main at Phase 0)
        │   conductor commits: PRD, ADRs, architecture, security, traceability,
        │                      SPEC.md + openapi.yaml per subsystem, then the RED-lock
        ├─ issue/12-redirect-resolver   (worktree; implementer commits; PR → integration)
        ├─ issue/11-link-store          (worktree; …)
        └─ issue/13-analytics           (worktree; …)
  final: one PR  maestro/<prd-slug> → main   (human reviews & merges)
```

- One integration branch **per run** (`maestro/<prd-slug>`), so each build is an isolated,
  reviewable delta.
- Subsystem branches `issue/<n>-<subsystem>` are cut **from the integration branch, after the
  RED suite is locked** (decision 3), so every implementer inherits the same frozen oracle.

### 4.1 Merge policy (decision locked)

- **Subsystem PR (`issue/* → integration`): machine-merged on green.** Gate-3 + Gate-4 + the
  RED-lock re-check are mechanical proof of correctness, so the machine merges these
  automatically once they pass.
- **Integration PR (`maestro/<prd-slug> → main`): human-merged.** This is the single
  human-in-the-loop review — one consolidated PR instead of N subsystem reviews. Branch
  protection on `main` (see §1) enforces it.

This is the HITL shift: the AI team commits on branches and merges its own *verified*
subsystem work into integration; the human owns the one merge that reaches `main`.

---

## 5. Where git actions attach to the state machine

Every git action hangs off a gate-pass transition that already exists:

| Transition | Git action |
|---|---|
| `/conduct` start | `preflight.py`; cut `maestro/<prd-slug>` from `main` |
| Phase 0 → Gate 0 pass (PRD frozen) | commit `docs/PRD.md`; run `prd-to-backlog` (gh) → **story** issues |
| Phase 1 → Gate 0.5 HITL pass (arch frozen) | commit `docs/adr/`, `architecture.md`, `security.md`, `traceability.md`; run `audit_traceability.py`; create **subsystem** issues |
| Phase 2 (decompose) | per subsystem, commit `SPEC.md` + `openapi.yaml` on integration |
| Phase 2 → Phase 3 boundary | lock the RED suite on integration; then cut `issue/<n>-<subsystem>` worktrees |
| Phase 3–4 (per subsystem) | implementer commits on its branch; on green gates, open + **machine-merge** subsystem PR → integration |
| End of run | open **integration → main** PR; **human** reviews and merges |

---

## 6. Reuse map

| Item | Source | Disposition |
|---|---|---|
| PRD → issues | `prd-to-backlog` | Reuse logic (tolerant `US`-key parsing, `prd-sync`/`src-sha` idempotent reconciliation). **Change: MCP → `gh`.** |
| Commit PRD/ADRs | — | Net-new `commit_artifacts.py`, gate-triggered docs commits. |
| Branch / no-main / PR | `commit` + `ship` (shape) | Reuse shape; **teeth = ported `commit-gate.sh` as a Maestro PreToolUse git hook.** Diverge from `ship`: stop subsystem flow at machine-merge-to-integration; the human merge is integration→main. |
| Worktrees | — | Net-new `worktree_manager.py`. |

---

## 7. Deliverables (to build, in order)

1. **`scripts/hook_git_gate.py`** + new matcher block in `hooks.json` (alongside
   `boundary-guard`). Denies commits/pushes to `main`/`master`; allows `maestro/<slug>` and
   `issue/<n>-<subsystem>`; enforces the `^issue/[0-9]+-[a-z0-9-]+$` branch shape. **Teeth first.**
2. **`scripts/preflight.py`** — the §1 precondition check.
3. **`scripts/commit_artifacts.py`** — gate-triggered docs commits with traceable messages
   (e.g. `docs(prd): freeze PRD [Gate 0]`).
4. **`scripts/audit_traceability.py`** — the §3.3 coverage gate.
5. **Subsystem-issue creation step** — reads `docs/traceability.md`, creates `type:subsystem`
   issues via `gh`, links them to story issues.
6. **Ported `prd-to-backlog` (gh-based)** as a Maestro skill.
7. **`ship`-shaped skill** — "open PR, stop at the right merge boundary" per §4.1.
8. **`scripts/worktree_manager.py`** — create/list/teardown `.maestro/worktrees/<subsystem>/`.
   Built **last** (most complex; complements, does not replace, the boundary guard: worktree =
   git-level isolation, boundary guard = path-level isolation).
9. **`/conduct` edits** — wire §5 into the state machine.

Sequence: teeth (1) → preconditions (2) → artifact commits (3) → traceability + issues (4,5)
→ story issues (6) → PR flow (7) → worktrees (8) → orchestration wiring (9).

---

## 8. Deferred / out of scope

- **Claude Code compatibility** — `gh` is the Antigravity choice; a Claude Code port may use
  a different GitHub path (MCP or otherwise). Adapt then.
- **Phase 5 deployment track** — unchanged by this plan.
