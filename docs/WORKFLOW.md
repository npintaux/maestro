# Maestro End-to-End Workflow

How a Maestro run turns a raw prompt into merged, tested code — the issue model, how each
subagent works with git, and how the pieces are reconciled and verified together.

This is the **operational** companion to two design documents:
- [`docs/version-control-plan.md`](version-control-plan.md) — *why* the version-control spine is
  shaped this way (the design decisions and their rationale).
- [`skills/conduct/SKILL.md`](../skills/conduct/SKILL.md) + its
  [`references/orchestration-state-machine.md`](../skills/conduct/references/orchestration-state-machine.md)
  — the state machine the conductor executes.

The founding thesis governs everything below: **under task pressure, an LLM subagent ignores
prose instructions.** So every non-negotiable is a *mechanical* script that exits non-zero or
emits `{"decision":"deny"}` — never a guardrail the model is trusted to obey. A rule that isn't
backed by a hook or an auditor does not exist.

---

## 1. Mental model

Three ideas carry the whole workflow. Hold these and the rest follows.

**a. One run = one integration branch.** At the start of a run the conductor cuts
`maestro/<prd-slug>` from `main`. Every artifact, every locked test suite, and every merged
subsystem lands there first. `main` is protected; no agent ever commits, pushes, or merges to it.
The only path into `main` is a single human-reviewed `integration → main` pull request at the end.

**b. Two orthogonal issue axes.** Product value and technical structure are decomposed
independently, so neither can be generated from the other:

```
 type:story     US-1 ───────┐        ┌─────── US-2        (PO-owned, from the PRD)
 (what users    US-3 ──┐    │        │
  want)                │    │        │
                    ┌──┴────┴────────┴──┐   many-to-many (the traceability matrix)
 type:subsystem   #11 link_store   #12 redirect_resolver   #13 analytics
 (how we build)   └── branch = worktree = one unit of parallel work
```

A story can span many subsystems; a subsystem can serve many stories. The link between them is an
explicit, gated artifact — `docs/traceability.md` — not something a subagent improvises.

**c. Three planes of isolation, each mechanically enforced.** A subagent is fenced in three
independent ways at once:

| Plane | Fence | Enforced by | Question it answers |
|---|---|---|---|
| **Path-level** | Boundary guard | `hook_boundary_guard.py` (PreToolUse on file writes) | *Which files may this agent edit?* |
| **Branch-level** | Git gate | `hook_git_gate.py` (PreToolUse on `run_command`) | *Which branches may this agent commit to / create?* |
| **Git-level** | Worktrees | `worktree_manager.py` | *Where does this agent's checkout physically live?* |

These are complementary, not redundant. The boundary guard stops an implementer from editing
another subsystem's *files*; the git gate stops it from committing to `main`; the worktree gives it
a physically separate checkout so parallel implementers never collide in the working tree.

---

## 2. Actors

The **Conductor** (`/conduct`) is the state machine. It holds zero authority to waive a gate —
phase progression is strictly conditional on `$? == 0` from a mechanical script. It never writes
domain code or tests itself; it dispatches specialist subagents with clean context boundaries and
runs the gate scripts between phases.

| Persona (skill) | Produces | `MAESTRO_ACTIVE_ROLE` | Writes allowed (boundary guard) |
|---|---|---|---|
| Product Owner (`/prd-validate`, `/prd-to-backlog`) | `docs/PRD.md`; `type:story` issues | — (root) | docs (no subsystem constraint) |
| Cloud Architect (`/architect-design`) | ADRs, `architecture.md`, `traceability.md` | — (root) | docs |
| Security Architect (`/secops-audit`) | `docs/security.md` | — (root) | docs |
| Subsystem Tech Lead (`/lead-decompose`) | `SPEC.md` + `openapi.yaml` per subsystem | — (root) | docs / subsystem contract |
| Test Architect (`/test-architect`) | contract + behavioral tests | `test-author` | `tests/contract/<sub>/`, `tests/behavioral/<sub>/` |
| Implementer (`/code-implement`) | domain code + unit/integration tests | `implementer` | `src/modules/<sub>/`, `tests/unit/<sub>/`, `tests/integration/<sub>/` |

The last two rows are the load-bearing separation: the Test Architect writes the oracle, the
Implementer writes the code, and **the boundary guard makes it mechanically impossible for the
implementer to edit the orthogonal tests** — so the tests can't be quietly bent to pass. See §4.

---

## 3. End-to-end walkthrough

Each phase transition fires a **git action**, run by a script that refuses on violation. The
sequence below is the spine; the gate scripts (`gate_controller.py run gate-N`) that guard each
phase are documented in the state-machine reference and omitted here for focus.

### Run start — preflight & integration branch

```bash
preflight.py                         # aborts the run on any non-zero exit
git switch -c maestro/<prd-slug> main # cut the per-run integration branch
```

`preflight.py` refuses to start unless **all** hold: cwd is a git worktree; an HTTPS `origin`
remote exists; `gh auth status` succeeds; the default branch is `main`; and **`main` has branch
protection**. That last check is not cosmetic — it is what makes "only the human merges to `main`"
real rather than prose. The git gate permits the `maestro/<slug>` branch creation because it matches
`INTEGRATION_BRANCH_RE`; it would deny, say, `git switch -c feature/foo`.

### Phase 0 → Gate 0 — PRD frozen, story issues born

The Product Owner produces `docs/PRD.md` (functional + all 7 GCP WAF non-functional requirements,
zero placeholders). On Gate 0 pass:

```bash
commit_artifacts.py prd          # freeze docs/PRD.md on integration
prd_backlog_sync.py --dry-run    # preview story-issue reconciliation
prd_backlog_sync.py              # create/update type:story issues via gh
```

This is where the **story axis** is created. See §5.1 for the reconciliation semantics.

### Phase 1 → Gate 0.5 — architecture frozen (HITL), subsystem issues born

The Architect and Security Architect produce the ADRs, `architecture.md`, `security.md`, and — the
artifact that links the two axes — `docs/traceability.md`. Three adversarial critic subagents
(resilience / cost / simplicity) file objections that the architect must resolve. **Gate 0.5 is a
non-bypassable human checkpoint**: the run pauses until a human approves the ADRs (`Approved-by:`).
On approval:

```bash
commit_artifacts.py architecture # freeze ADRs, architecture.md, security.md, traceability.md
audit_traceability.py            # gate the story↔subsystem matrix (bites; see §5.2)
create_subsystem_issues.py --dry-run
create_subsystem_issues.py       # create type:subsystem issues via gh
```

This is where the **subsystem axis** is created and mapped to stories (§5.3). **The subsystem issue
numbers are born here, and those numbers become the branch names** — so this step must precede any
branch or worktree. The conductor captures the `subsystem → issue-number` map from the JSON output;
Phase 2 and Phase 3 both need it.

### Phase 2 → Gate 2 — contracts frozen (per subsystem)

Each Tech Lead produces `src/modules/<subsystem>/openapi.yaml` + `SPEC.md`. On Gate 2 pass:

```bash
commit_artifacts.py spec --subsystem <name> --issue <n>   # freeze the contract on integration
```

### Phase 3 — orthogonal tests generated, RED suite locked, worktrees cut

For each subsystem, the Test Architect (role `test-author`) writes contract and behavioral tests
**derived strictly from the PRD + `openapi.yaml`, never from implementation code**. Then the suite
is *locked*:

```bash
verify_red_suite.py lock --subsystem <name>   # prove RED, capture SHA256 manifest
commit_artifacts.py tests --subsystem <name>  # freeze the LOCKED suite on integration
```

`lock` runs the suite against the (absent) implementation, asserts it genuinely fails (pytest exits
non-zero — a suite that passes with no implementation is a broken oracle), and records a SHA256
hash of every test file into `.maestro/red_lock/<name>.json`. `commit_artifacts.py tests` then
freezes the contract + behavioral tests **and that manifest** onto the integration branch.

Only after **every** subsystem is locked and committed does the conductor cut the worktrees:

```bash
# spec.json: [{"subsystem":"redirect_resolver","issue":12}, {"subsystem":"link_store","issue":11}]
worktree_manager.py create --integration maestro/<prd-slug> --spec spec.json --dry-run
worktree_manager.py create --integration maestro/<prd-slug> --spec spec.json
```

This ordering is the **lock-before-parallel** invariant: because each worktree is cut *from the
integration branch after the manifest was committed there*, every implementer inherits the identical
frozen oracle. If worktrees were cut first, they would contain no manifest and Gate 4 would have
nothing to verify. Each worktree lives at `.maestro/worktrees/<subsystem>/` on branch
`issue/<n>-<slug>` (slug = snake→kebab, e.g. `redirect_resolver` → `issue/12-redirect-resolver`).

### Phase 4 — implementation & machine-merge (per subsystem, in parallel)

Each Implementer (role `implementer`) works **inside its own worktree**, deriving behavior from
`SPEC.md` + `openapi.yaml`. It runs the TDD loop and its own unit tests; it cannot touch the
orthogonal contract/behavioral suite (boundary guard) and cannot commit to `main` (git gate). When
the code-quality and coverage gates pass, the subsystem ships:

```bash
cd .maestro/worktrees/<subsystem>
ship_pr.py subsystem --integration maestro/<prd-slug> --dry-run
ship_pr.py subsystem --integration maestro/<prd-slug>
```

`ship_pr.py subsystem` **re-runs a fresh proof** — `gate-3` + `gate-4` + an explicit `redlock`
re-check — and squash-merges the PR into integration **only on all-green**, deleting the branch. A
red proof leaves the PR open and exits non-zero; the conductor's bounded 3-attempt remediation loop
dispatches a repair task and re-ships. It refuses any base that isn't the integration branch and any
head that isn't a subsystem branch. See §6.

### End of run — the one human merge

Once every subsystem PR has merged into integration:

```bash
ship_pr.py integration --integration maestro/<prd-slug> --base main   # opens PR, NEVER merges
worktree_manager.py teardown                                          # remove worktrees; keep branches
```

`ship_pr.py integration` opens the single consolidated `maestro/<prd-slug> → main` PR and **stops —
it contains no code path that merges to `main`.** The human reviews one delta and merges, backed by
the branch protection that preflight verified.

---

## 4. How each subagent works with git

A subagent never reasons about branch policy or file scope — those are enforced *around* it by
hooks that intercept its tool calls before they execute. The subagent just does its job; the fences
hold regardless of what its prompt talks it into.

### 4.1 Path-level: the boundary guard (`hook_boundary_guard.py`)

Registered in `hooks.json` as a PreToolUse hook on the file-mutating tools
(`write_to_file`, `replace_file_content`, `multi_replace_file_content`). Before any write, it reads
`MAESTRO_ACTIVE_SUBSYSTEM` and `MAESTRO_ACTIVE_ROLE` from the environment the conductor set for that
subagent, extracts the target path from the tool payload, and calls `check_boundaries.check_boundary`:

- **No active subsystem** (Conductor / Architect / PO at repo root) → **allow**. Root personas write
  docs freely.
- **`test-author`** → may write only `tests/contract/<sub>/` and `tests/behavioral/<sub>/`.
- **`implementer`** → may write only `src/modules/<sub>/`, `tests/unit/<sub>/`,
  `tests/integration/<sub>/`. Note the deliberate asymmetry: **the implementer cannot write the
  contract/behavioral tests** — those are the independent Gate 4 oracle — but *keeps* its unit tests
  to preserve a tight TDD loop.
- **Unknown role** → **fail-closed**: no paths permitted, every write denied. (Contrast with the git
  gate, which fails *open* — see below. The distinction is deliberate: an unknown *identity* is
  suspicious and locked down; an unparseable *command* is probably unrelated and let through.)
- Absolute paths, `..` traversal, and anything resolving outside the repo root are rejected.

On a violation the hook returns `{"decision":"deny","reason":"PreToolUse Boundary Guard: …"}` and
the write never happens.

### 4.2 Branch-level: the git gate (`hook_git_gate.py`)

Registered as a PreToolUse hook on `run_command`. It tokenizes the command line (splitting on
`&&`, `||`, `|`, `;` so chained commands are each inspected), finds every `git` invocation, and
enforces three rules — the single source of truth for branch topology:

1. **No commit on a protected branch** — `git commit` is denied when the current branch is
   `main`/`master`. (A subprocess `git commit` run by a *script* like `commit_artifacts.py` is not
   hook-intercepted, so each such script re-enforces this rule itself.)
2. **No push to a protected branch** — `git push` is denied when its refspec targets `main`/`master`,
   or when it's a bare push while sitting on a protected branch.
3. **Only Maestro-shaped branches may be created** — `git checkout -b` / `git switch -c` /
   `git branch <name>` are denied unless the name matches `INTEGRATION_BRANCH_RE`
   (`^maestro/[a-z0-9][a-z0-9._-]*$`) or `SUBSYSTEM_BRANCH_RE` (`^issue/[0-9]+-[a-z0-9-]+$`).
   Enforcing shape *at creation* means an agent can never end up standing *on* an off-process
   branch, which is why rule 1 only has to police `main`/`master`.

The gate **fails open**: anything it cannot confidently evaluate (not a git command, unparseable
payload, undeterminable current branch) is allowed, so a bug in the gate never blocks unrelated work.
Only a *confident* violation denies.

### 4.3 Git-level: worktrees (`worktree_manager.py`)

Parallel implementers can't share one working tree. `worktree_manager.py create` cuts one
`issue/<n>-<slug>` branch per subsystem, each checked out in its own directory under
`.maestro/worktrees/<subsystem>/`, all cut from the integration branch. It bites where it must:

- Worktrees are cut **only from the integration branch** — a base of `main`/`master` (or any branch
  not matching `INTEGRATION_BRANCH_RE`) is refused. The no-branch-off-`main` rule starts here.
- The branch name is built `issue/<n>-<slug>` using the *same* snake→kebab slug function shared with
  subsystem-issue creation, and validated against `SUBSYSTEM_BRANCH_RE` before any `git worktree add`.
- **No clobber**: a path already occupied by a *different* branch, or a non-worktree directory, is an
  error, not an overwrite. An already-correct worktree is an idempotent skip (resume-safe).

`teardown` removes the worktrees at end of run but leaves the branches intact (ship already deletes a
subsystem branch when it merges).

---

## 5. The two-axis issue model, in detail

### 5.1 Story issues (`prd_backlog_sync.py`)

The PRD, once frozen by `/prd-validate`, contains structured `US-N` stories with Given/When/Then
acceptance criteria — so turning them into issues needs **no creative drafting**, and the whole
reconciliation is a deterministic script (the thesis: the load-bearing step is mechanical, not an
LLM). It parses each `US-N` section of the PRD and reconciles against existing GitHub issues:

- **Identity** is recovered from a hidden marker in the issue body,
  `<!-- prd-sync: key=us<n> src-sha=<12-hex> -->` (authoritative), falling back to a `[US<n>]` title
  tag. Matching on a marker — not on fuzzy title text — is what makes reconciliation idempotent.
- **`src-sha`** is a 12-char SHA1 of the whitespace-normalized PRD section: a stable change key. A
  matching `src-sha` means "unchanged"; a different one means "the PRD section was edited."
- **Reconcile verbs:**
  - **create** — no issue for this `us<n>` → create with labels `type:story` + `status:draft` +
    a derived MoSCoW `priority:*` (from must/should/could/won't-have language in the section).
  - **update** — issue exists, `src-sha` differs → refresh body + `src-sha`. **Never re-adds
    `status:draft`** — the Product Owner owns publish state, and a PRD edit must not silently
    un-publish a story.
  - **skip** — `src-sha` matches → no write at all.
  - **removed** — an issue exists for a `us<n>` no longer in the PRD → **flagged, never auto-closed
    or deleted.** Maestro reports it for a human to decide.

Story issues are created `status:draft`; the PO publishes by removing that label. This is the same
engine the `/prd-to-backlog` skill drives interactively (dry-run → present → apply).

### 5.2 The traceability matrix & its gate (`audit_traceability.py`)

`docs/traceability.md` is a markdown table the architect writes in Phase 1 — the first moment both
axes exist. Each row's first cell names a `US-N`; the remaining cells name the subsystem(s) that
realize it:

```markdown
| Story | Subsystems                          |
|-------|-------------------------------------|
| US-1  | src/modules/link_store              |
| US-2  | src/modules/analytics, link_store   |
```

`audit_traceability.py` cross-references the matrix against `US-N` extracted from `docs/PRD.md` and
subsystems extracted from `docs/architecture.md` (`src/modules/<name>/`) — using the *same* regexes
as the sibling audit gates, so the creator and the gate can never disagree. It **exits non-zero** on:

- an **orphaned story** — a PRD `US-N` that maps to no subsystem (value nobody builds); `TBD`/`none`
  placeholder cells count as unmapped;
- a **speculative subsystem** — an architecture subsystem serving no story (build nobody asked for);
- a **dangling story reference** — a matrix row citing a `US-N` not in the PRD;
- an **unknown subsystem reference** — a matrix cell naming a subsystem not in the architecture.

The many-to-many mapping is thus a *validated* artifact, gated before any subsystem issue exists.

### 5.3 Subsystem issues (`create_subsystem_issues.py`)

Run at the Gate 0.5 → Phase 2 handoff, this reads `docs/traceability.md` (reusing
`audit_traceability._parse_matrix`, so creator and gate share one parser) and creates **one
`type:subsystem` tracking issue per subsystem**, each cross-linking *upward* to the story issues it
serves. Identity is a hidden marker `<!-- maestro-subsystem: name=<name> -->`; the body lists the
served stories with their story-issue numbers (`- US-1 (#42)`). It is idempotent (re-running updates
in place) and it **bites**: if a subsystem serves a story that has *no* GitHub story issue, that is a
hard, pre-write error — no half-created backlog. The subsystem issue **number** is what the branch
`issue/<n>-<slug>` and its worktree are named for, tying the technical axis back to a concrete
GitHub work item.

So the mapping flows: **PRD → story issues** (5.1); **architecture → subsystems**; **matrix links
the two and is gated** (5.2); **subsystem issues carry the links and mint the numbers** (5.3);
**numbers become branches/worktrees** (§3, §4.3).

---

## 6. How things are reconciled and tested together

### The RED-lock: an oracle that can't be gamed

The central testing guarantee is that the tests are an *independent* oracle. Two mechanisms enforce
it:

1. **Orthogonal authorship.** The Test Architect (`test-author`) writes contract/behavioral tests
   from the PRD + OpenAPI only, and the boundary guard forbids the Implementer from ever editing
   those files (§4.1). The implementer is told not to even read them as a spec.
2. **Cryptographic RED-lock.** `verify_red_suite.py lock` proves the suite fails against the absent
   implementation (a suite that passes with no code is meaningless) and records a SHA256 manifest of
   every test file. `verify_red_suite.py check` (run inside Gate 4) verifies the manifest is present
   and the files are byte-for-byte untampered before coverage runs. If an implementer somehow altered
   a locked test, the hashes wouldn't match and the gate fails.

Because the locked manifest and tests are committed to the integration branch *before* worktrees are
cut, every subsystem worktree inherits the identical, verifiable oracle.

### Per-subsystem gates (`run_gate_suite.sh` via `gate_controller.py`)

Inside each worktree the implementer's work is verified mechanically:

- **gate-3 (code quality)** — `ruff check`, `ruff format --check`, `mypy --strict`, and
  `audit_implementation.py` (one class per file, Google docstrings, clean-architecture layering).
- **gate-4 (test & coverage)** — re-runs the RED-lock `check`, then `audit_test_coverage.py`, then
  pytest at **100% statement coverage** (`--cov=src --cov-fail-under=100`).

`gate_controller.py` tracks attempts in `.maestro/gate_state.json` and enforces the bounded
remediation loop: exit `0` = pass; exit `1` = fail (dispatch a targeted repair, retry, max 3); exit
`3` = circuit breaker tripped → **halt and escalate to the human**. The conductor has no authority to
override.

### Bringing subsystems together

Subsystems are integrated **one machine-merge at a time**, each proven fresh:

- `ship_pr.py subsystem` re-runs `gate-3` + `gate-4` + `redlock` at ship time (not trusting a prior
  green — a stale green is how a regression lands) and squash-merges into the integration branch only
  on all-green. Each merge lands verified work; the integration branch is always green.
- After all subsystems merge, `ship_pr.py integration` opens the single `integration → main` PR and
  never merges it. The human reviews one consolidated, fully-tested delta and performs the only merge
  that reaches `main`.

This is the human-in-the-loop shift: **the AI team merges its own *verified* subsystem work into
integration; the human owns the one merge into `main`.**

### Idempotency & resume

Every git-touching script is resume-safe, so a run interrupted mid-flight can be re-driven without
duplicating work:

- `commit_artifacts.py` — an unchanged artifact set is a no-op success ("already frozen").
- `prd_backlog_sync.py` / `create_subsystem_issues.py` — marker-keyed reconciliation: re-running
  skips unchanged issues and updates in place, never duplicating.
- `worktree_manager.py` — an already-correct worktree is skipped; it refuses to clobber.
- `ship_pr.py` — reuses an already-open PR (via `gh pr list`) rather than creating a second.

---

## 7. Quick reference

### Branches
| Shape | Regex | Who / what |
|---|---|---|
| `main` / `master` | (protected) | Human-merge only; agents never touch it |
| `maestro/<prd-slug>` | `^maestro/[a-z0-9][a-z0-9._-]*$` | Per-run integration branch |
| `issue/<n>-<slug>` | `^issue/[0-9]+-[a-z0-9-]+$` | One subsystem, one worktree |

### GitHub labels & markers
| Kind | Label(s) | Body marker |
|---|---|---|
| Story issue | `type:story`, `status:draft`, `priority:*` | `<!-- prd-sync: key=us<n> src-sha=<12hex> -->` |
| Subsystem issue | `type:subsystem` | `<!-- maestro-subsystem: name=<name> -->` |

### Environment (set by the conductor per subagent)
| Var | Values | Effect |
|---|---|---|
| `MAESTRO_ACTIVE_SUBSYSTEM` | subsystem name / unset | Scopes the boundary guard; unset = root persona, docs-only |
| `MAESTRO_ACTIVE_ROLE` | `test-author` / `implementer` / unset | Which paths the guard permits |

### Scripts by transition
| Transition | Script(s) |
|---|---|
| Run start | `preflight.py` |
| Gate 0 (PRD) | `commit_artifacts.py prd`; `prd_backlog_sync.py` |
| Gate 0.5 (arch) | `commit_artifacts.py architecture`; `audit_traceability.py`; `create_subsystem_issues.py` |
| Gate 2 (contract) | `commit_artifacts.py spec --subsystem <n> --issue <n>` |
| Phase 3 (RED-lock) | `verify_red_suite.py lock`; `commit_artifacts.py tests` |
| Phase 3→4 boundary | `worktree_manager.py create` |
| Phase 4 (ship) | `ship_pr.py subsystem` |
| End of run | `ship_pr.py integration`; `worktree_manager.py teardown` |
| Always-on hooks | `hook_boundary_guard.py`, `hook_git_gate.py` (PreToolUse) |
