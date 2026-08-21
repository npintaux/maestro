---
name: ship
description: Delivers Maestro work by pull request under a mechanical merge policy — subsystem branches (issue/<n>-<slug>) are machine-merged into the per-run integration branch only after a fresh local re-run of the mechanical proof (gate-3 + gate-4 + RED-lock) is green, and the consolidated integration→main PR is opened but never merged (the single human review). Use to open/merge a completed subsystem PR or to raise the final integration PR ("/ship", "merge this subsystem", "open the integration PR", "land the run"). Do NOT use to merge into main or land the integration branch — that merge is the human reviewer's action, never Maestro's; do not use for docs freezes (commit_artifacts) or during active implementation (use /code-implement).
---

# /ship  (mechanical merge policy)

Deliver completed work by pull request. There are exactly two boundaries, and the policy at
each is enforced by a script that **refuses** rather than by prose the model is trusted to follow:

- **Subsystem** (`issue/<n>-<slug>` → the per-run integration branch `maestro/<slug>`):
  **machine-merged on green.**
- **Integration** (`maestro/<slug>` → `main`): **opened, never merged** — the one human review.

The SDD `ship` skill told the model "never merge red" and "merge into the right branch"; under
task pressure that does not hold. So the merge policy lives in
`${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/ship_pr.py`, and this skill
only drives it.

## When to use
- A subsystem's implementation is complete on its `issue/<n>-<slug>` branch and should land on
  integration.
- All subsystems have merged and you want to raise the final integration→main PR for the human.

## When NOT to use
- Freezing docs/spec artifacts (use `commit_artifacts.py`).
- Writing code or tests, or fixing a red gate (use `/code-implement`, `/test-architect`).
- Merging to `main` yourself — Maestro never does; the human merges the integration PR.

## Subsystem delivery (machine-merge on green)

```
python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/ship_pr.py" \
  subsystem --integration maestro/<slug> [--dry-run]
```

The script, run from the subsystem worktree:

1. **Refuses the wrong topology.** The base must be the integration branch (`maestro/<slug>`);
   targeting `main`/`master` is rejected. The head must be `issue/<n>-<slug>`; the issue number
   and subsystem are derived from it.
2. **Re-runs the mechanical proof fresh** — `gate-3` (code quality) + `gate-4` (test coverage,
   which re-runs RED-lock) + an explicit `redlock` re-check. This is proof, not trust in a prior
   green.
3. **Opens the PR** (`Closes #n`; reuses an already-open PR — idempotent).
4. **Merges iff green.** On all-green proof it squash-merges and deletes the branch. If any gate
   is red, the PR is left open and it **exits non-zero without merging**. Fix and re-ship.

## Integration delivery (open, never merge)

```
python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/ship_pr.py" \
  integration --integration maestro/<slug> [--base main]
```

Opens the consolidated `maestro/<slug> → main` PR and **stops**. No code path here merges;
this is deliberately the single human-in-the-loop review, backed by branch protection on `main`
(see `preflight.py`). Relay the PR URL to the human.

## Procedure
1. Identify the boundary: shipping a subsystem, or raising the integration PR.
2. **Dry-run first** to see the proof result / plan without writing.
3. Run the real command. For a subsystem, on green it machine-merges; on red it stops — do not
   override, fix the gate via `/code-implement` and re-ship.
4. Relay the script's JSON report (PR URL, proof per gate, merged?) to the user.

## Guardrails
- **Never merge red.** The merge is gated on a fresh gate re-run; a red proof refuses to merge.
- **Never merge to `main`.** Only a human merges the integration PR; the script never issues that
  merge.
- **Subsystem PRs target integration only** — never `main`, never another subsystem branch.
- **One boundary per invocation.** Shipping a subsystem does not also raise the integration PR.

## Common Rationalizations
| The excuse | The reality |
|---|---|
| "The gates passed earlier, just merge." | Proof is re-run at ship time. Trusting a stale green is how a regression lands. |
| "Only RED-lock is failing, override it." | RED-lock is the frozen oracle. A red RED-lock means the contract broke — never override. |
| "I'll merge the integration PR to finish the run." | Maestro never merges to `main`. That merge is the human's, by design. |
| "Base it on `main` to skip the integration branch." | Subsystem PRs must target `maestro/<slug>`. The script refuses `main`. |

## Verification
Before completing, verify:
- [ ] You ran `scripts/ship_pr.py` (did not hand-merge with `gh`).
- [ ] For a subsystem: the base was `maestro/<slug>`, the proof re-ran green, and the merge was
      squash + delete-branch — or it was red and you did **not** merge.
- [ ] For integration: the PR was opened `maestro/<slug> → main` and left **unmerged** for the human.
- [ ] You relayed the PR URL and per-gate proof to the user.

## References
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/ship_pr.py` — the merge-policy engine.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/run_gate_suite.sh` — gate-3/gate-4/redlock proof.
- `docs/version-control-plan.md` §4.1 — the merge policy this skill enforces.
