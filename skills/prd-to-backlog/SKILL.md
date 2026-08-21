---
name: prd-to-backlog
description: Reconciles the frozen docs/PRD.md user stories into GitHub type:story issues via the gh CLI, using a mechanical sync script that hashes each PRD section (src-sha) to create new stories, update changed ones, skip unchanged ones, and flag removed ones without duplicates. (Product Owner persona.) Use when the PO wants to turn a validated PRD into a GitHub backlog or reconcile issues after PRD changes ("/prd-to-backlog", "sync stories to GitHub", "populate the backlog"). Do not use for technical decomposition (use /lead-decompose) or writing code (use /code-implement).
---

# /prd-to-backlog  (Product Owner — Gate 0)

Turn the frozen product intent (`docs/PRD.md`) into a drafted GitHub backlog of **`type:story`**
issues. This is the **Product Owner** persona; it produces one axis of the two-axis issue model.
The *engineering* axis (`type:subsystem` issues) is created separately, later, by
`/lead-decompose`'s subsystem step — neither axis generates the other; they are bridged by
`docs/traceability.md`.

## When to use
- `docs/PRD.md` is frozen (via `/prd-validate`) and the PO wants the corresponding story issues.
- Reconciling the backlog after the PRD changed (add/update/skip/flag, incrementally).

## When NOT to use
- Technical decomposition, OpenAPI/SPEC authoring, or **subsystem** issues (use `/lead-decompose`).
- Writing application or test code (use `/code-implement`, `/test-architect`).
- Opening or merging PRs (that is the ship/commit flow).

## Why this is a script, not prose (the Maestro thesis)

The upstream SDD skill left the whole job — parsing story keys, hashing PRD sections, reading
markers, deciding create/update/skip, and issuing the API calls — to the model. Under task
pressure that produces duplicate issues, missed changes, and clobbered PO edits: prose does not
bite. So the load-bearing work is mechanical here. Because `/prd-validate` already freezes a PRD
whose Section 5 carries structured `US-N` stories with Given/When/Then acceptance criteria, the
sync needs **no creative drafting** — it is deterministic reconciliation:

```
python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/prd_backlog_sync.py" \
  --repo <org>/<repo> [--dry-run]
```

The script (`scripts/prd_backlog_sync.py`) owns the entire load-bearing contract:

- **Identity & change detection.** Each story is keyed `us<n>` (parsed tolerantly: `US1`,
  `[US1]`, `US-1`, `US 1`). Change is detected by `src-sha`, a hash of the story's **PRD section**
  (stable run to run — never a fuzzy diff of the drafted body).
- **Reconciliation**, keyed on the marker `<!-- prd-sync: key=us<n> src-sha=… -->` (with a
  `[USn]` title fallback for legacy issues):
  - **New** → create with labels `type:story`, `status:draft`, and the derived priority.
  - **Changed** (`src-sha` differs) → update the body and refresh `src-sha`. It **does not**
    touch `status:draft` — publish state belongs to the PO and is never silently re-imposed.
  - **Unchanged** → skip (no API write).
  - **Removed** (issue exists, story gone from PRD) → left intact, **flagged** for the PO;
    never auto-closed or deleted.
- **GitHub access** is `gh -R <org>/<repo> …` only (the `permissioned-github` contract: no
  `curl`, no direct API, HTTPS). Priority is *derived, not demanded* (MoSCoW terms in the story
  text); absence is a note, not a failure.

## Procedure
1. **Confirm the PRD is frozen.** `docs/PRD.md` must exist with a Section 5 of `US-N` stories.
2. **Dry-run first** (`--dry-run`) and show the PO the plan: which stories are new / changed /
   unchanged / removed, and the derived priority for each. Nothing is written.
3. **Resolve missing intent with the PO, not by guessing.** If a story's persona, value, or
   acceptance criteria are genuinely missing/ambiguous in the PRD, stop and ask the PO — then
   fix it in `docs/PRD.md` and re-run (the PRD is the source of truth, not the issue).
4. **Apply** (drop `--dry-run`). The script creates/updates/skips and flags removed stories.
5. **Present the report.** Relay the JSON summary — creations, updates, skips, and every
   removed-story warning — to the PO for review.

## Guardrails (the responsibility line)
- **Drafts only.** Issues are created with `status:draft`; the PO publishes by removing it. The
  script never removes `status:draft`.
- **Never close or delete** an issue for a removed story — flag it and let the human decide.
- This skill **never** writes `SPEC.md`, subsystem issues, or code. Product intent is born in
  GitHub (PO); its technical form is born in the repo (engineering) via `/lead-decompose`.

## Common Rationalizations
| The excuse | The reality |
|---|---|
| "I'll create the issues by hand with `gh`." | Hand-issuing loses idempotency: you will duplicate issues and miss changes. Run the sync script — it reconciles on `src-sha`. |
| "I'll re-draft every issue each run." | Unchanged stories (`src-sha` matches) must trigger **no** write — notification spam and lost history otherwise. |
| "This story was dropped; I'll close its issue." | Never auto-close. Removed stories are flagged for the PO. |
| "I'll re-add `status:draft` when I update the body." | Publish state is the PO's. Updates refresh content only, never the draft label. |

## Verification
Before exiting, verify:
- [ ] You ran `scripts/prd_backlog_sync.py` (did **not** hand-issue `gh` calls) against `docs/PRD.md`.
- [ ] You presented a `--dry-run` plan to the PO before writing.
- [ ] The report's exit was clean (exit 0); any `gh` failure was surfaced, not ignored.
- [ ] Removed stories were left intact and flagged — none were closed or deleted.
- [ ] You created no `SPEC.md`, subsystem issues, or code.

## References
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/prd_backlog_sync.py` — the mechanical PRD→backlog reconciler.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/create_subsystem_issues.py` — the engineering-axis counterpart (`type:subsystem`), run later by `/lead-decompose`.
- `docs/version-control-plan.md` §3 — the two-axis issue model and the traceability bridge.
