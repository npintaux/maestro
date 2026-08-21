"""Ship a Maestro branch by pull request, enforcing the merge policy mechanically.

The SDD ``ship`` skill leaves "never merge red" and "merge to the right place" to prose the
model is asked to follow. Under the Maestro thesis that does not bite, so the merge *policy*
lives here as code that refuses:

  * **Subsystem PR** (``issue/<n>-<slug>`` -> the per-run integration branch ``maestro/<slug>``):
    **machine-merged on green.** "Green" is not remote CI trust — it is a fresh local re-run of
    the mechanical proof (gate-3 code-quality + gate-4 test-coverage + an explicit RED-lock
    re-check). If any gate is red, the PR is opened/left open but **not merged** (exit non-zero).
    The merge base must be the integration branch; targeting ``main``/``master`` is refused.

  * **Integration PR** (``maestro/<slug>`` -> ``main``): **opened, never merged.** This is the
    single human-in-the-loop review. No code path in integration mode issues a merge; asking for
    one is a hard error. Branch protection on ``main`` (see preflight.py) is the backstop.

Every GitHub call is ``gh -R <org>/<repo> …`` (permissioned-github). Command execution and the
gate proof are injected, so the policy is unit-testable without a repo, real gates, or network;
``--dry-run`` reports the plan without any write or merge.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

try:
    from scripts.hook_git_gate import (
        INTEGRATION_BRANCH_RE,
        PROTECTED_BRANCHES,
        SUBSYSTEM_BRANCH_RE,
    )
except ImportError:  # pragma: no cover - direct-invocation bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.hook_git_gate import (
        INTEGRATION_BRANCH_RE,
        PROTECTED_BRANCHES,
        SUBSYSTEM_BRANCH_RE,
    )

Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]
# A gate proof runner: given (stage, subsystem) -> (returncode, combined_output). 0 == passed.
GateRunner = Callable[[str, str], "tuple[int, str]"]
# A frontend probe: given a subsystem -> True iff it has a front-end to conformance-check.
FrontendProbe = Callable[[str], bool]

# The mechanical proof a subsystem PR must pass before the machine merges it (in order). A subsystem
# with a front-end (src/modules/<sub>/frontend/) also re-runs gate-frontend, appended at ship time.
SUBSYSTEM_PROOF_STAGES = ("gate-3", "gate-4", "redlock")

_ISSUE_URL_RE = re.compile(r"/(?:pull|issues)/(\d+)")
# issue/<n>-<slug> -> capture the number so the PR body can carry `Closes #n`.
_ISSUE_NUM_RE = re.compile(r"^issue/(\d+)-")

_RUN_GATE_SUITE = str(Path(__file__).resolve().parent / "run_gate_suite.sh")


@dataclass
class GateResult:
    stage: str
    passed: bool
    output: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"stage": self.stage, "passed": self.passed, "output": self.output[-2000:]}


@dataclass
class ShipReport:
    """Outcome of a ship (PR + policy) operation."""

    mode: str  # "subsystem" | "integration"
    repo: str | None = None
    head: str | None = None
    base: str | None = None
    dry_run: bool = False
    pr_url: str | None = None
    pr_number: int | None = None
    merged: bool = False
    proof: list[GateResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "repo": self.repo,
            "head": self.head,
            "base": self.base,
            "dry_run": self.dry_run,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "merged": self.merged,
            "proof": [g.to_dict() for g in self.proof],
            "warnings": self.warnings,
            "errors": self.errors,
            "note": self.note,
        }


def _default_runner(cmd: Sequence[str]) -> tuple[int, str, str]:
    import subprocess

    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]!r}"
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _default_gate_runner(stage: str, subsystem: str) -> tuple[int, str]:  # pragma: no cover
    rc, out, err = _default_runner(["bash", _RUN_GATE_SUITE, stage, subsystem])
    return rc, (out + err)


def _default_frontend_probe(subsystem: str) -> bool:  # pragma: no cover - touches the filesystem
    """True iff the subsystem has a front-end tree that gate-frontend must conformance-check."""
    return Path(f"src/modules/{subsystem}/frontend").is_dir()


def _resolve_repo(run: Runner) -> tuple[str | None, str | None]:
    rc, out, err = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if rc != 0 or not out.strip():
        detail = err.strip() or out.strip()
        return None, f"could not resolve repository via `gh repo view`: {detail}"
    return out.strip(), None


def _resolve_current_branch(run: Runner) -> str | None:
    rc, out, _ = run(["git", "branch", "--show-current"])
    return out.strip() or None if rc == 0 else None


def _existing_pr_url(run: Runner, repo: str, head: str, base: str) -> tuple[str | None, int | None]:
    """Return (url, number) of an open PR for head->base, or (None, None)."""
    rc, out, _ = run(
        ["gh", "pr", "list", "-R", repo, "--head", head, "--base", base, "--state", "open",
         "--json", "number,url", "--limit", "1"]
    )
    if rc != 0:
        return None, None
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None, None
    if isinstance(data, list) and data:
        return data[0].get("url"), data[0].get("number")
    return None, None


def _open_pr(run: Runner, repo: str, head: str, base: str, title: str, body: str,
             report: ShipReport) -> bool:
    """Open a PR (reusing an open one). True on success; records url/number/errors."""
    url, number = _existing_pr_url(run, repo, head, base)
    if url:
        report.pr_url, report.pr_number = url, number
        report.warnings.append(f"reusing existing open PR {url}")
        return True
    rc, out, err = run(
        ["gh", "pr", "create", "-R", repo, "--base", base, "--head", head,
         "--title", title, "--body", body]
    )
    if rc != 0:
        report.errors.append(f"`gh pr create` failed: {err.strip() or out.strip()}")
        return False
    report.pr_url = out.strip().splitlines()[-1].strip() if out.strip() else None
    m = _ISSUE_URL_RE.search(out)
    report.pr_number = int(m.group(1)) if m else None
    return True


def _run_proof(
    gate_runner: GateRunner,
    subsystem: str,
    report: ShipReport,
    frontend_probe: FrontendProbe,
) -> bool:
    """Run the subsystem's mechanical proof; record each stage. Returns True iff all green.

    UI subsystems (those with a ``frontend/`` tree) also re-run ``gate-frontend`` so the PR's
    fresh proof covers UI conformance; backend-only subsystems skip it.
    """
    stages = list(SUBSYSTEM_PROOF_STAGES)
    if frontend_probe(subsystem):
        stages.append("gate-frontend")
    all_green = True
    for stage in stages:
        rc, output = gate_runner(stage, subsystem)
        passed = rc == 0
        report.proof.append(GateResult(stage=stage, passed=passed, output=output))
        if not passed:
            all_green = False
    return all_green


def ship_subsystem(
    integration_branch: str,
    subsystem: str | None = None,
    issue: int | None = None,
    current_branch: str | None = None,
    repo: str | None = None,
    runner: Runner | None = None,
    gate_runner: GateRunner | None = None,
    frontend_probe: FrontendProbe | None = None,
    dry_run: bool = False,
    no_merge: bool = False,
) -> ShipReport:
    """Open the subsystem PR (issue/* -> integration) and machine-merge it only on green proof."""
    run = runner or _default_runner
    gates = gate_runner or _default_gate_runner
    probe = frontend_probe or _default_frontend_probe
    report = ShipReport(mode="subsystem", base=integration_branch, dry_run=dry_run)

    # --- Mechanical guards: the branch topology must be exactly right, or we refuse. ---
    if integration_branch in PROTECTED_BRANCHES or not INTEGRATION_BRANCH_RE.match(
        integration_branch
    ):
        report.errors.append(
            f"refusing to ship: base '{integration_branch}' is not a per-run integration branch "
            "(maestro/<slug>). Subsystem PRs never target main/master."
        )
        return report

    head = current_branch or _resolve_current_branch(run)
    report.head = head
    if not head or not SUBSYSTEM_BRANCH_RE.match(head):
        report.errors.append(
            f"refusing to ship: current branch '{head}' is not a subsystem branch "
            "(issue/<n>-<slug>)."
        )
        return report

    if issue is None:
        m = _ISSUE_NUM_RE.match(head)
        issue = int(m.group(1)) if m else None
    if subsystem is None:
        subsystem = head.split("-", 1)[1] if "-" in head.split("/", 1)[-1] else ""
    if not subsystem:
        report.errors.append(f"could not derive subsystem from branch '{head}'.")
        return report

    if repo is None:
        repo, err = _resolve_repo(run)
        if err:
            report.errors.append(err)
            return report
    assert repo is not None  # _resolve_repo yields a repo string whenever err is None
    report.repo = repo

    # --- Proof: a fresh local re-run of the mechanical gates. Red proof => no merge. ---
    green = _run_proof(gates, subsystem, report, probe)

    closes = f"Closes #{issue}\n\n" if issue is not None else ""
    title = f"feat({subsystem}): deliver subsystem [{head}]" + (f" (#{issue})" if issue else "")
    body = (
        f"{closes}Subsystem `{subsystem}` implementation, merging into the integration branch "
        f"`{integration_branch}`.\n\n"
        "Mechanical proof (re-checked at ship time):\n"
        + "\n".join(f"- {'✅' if g.passed else '❌'} {g.stage}" for g in report.proof)
    )

    if dry_run:
        report.note = "dry-run: no PR opened, no merge"
        if not green:
            report.errors.append("proof is RED — a real ship would refuse to merge.")
        return report

    if not _open_pr(run, repo, head, integration_branch, title, body, report):
        return report

    if not green:
        report.errors.append(
            "subsystem proof is RED (see 'proof'); PR left open, NOT merged. Fix and re-ship."
        )
        return report

    if no_merge:
        report.note = "proof green; PR opened but --no-merge set, so left for manual merge."
        return report

    rc, out, err = run(["gh", "pr", "merge", "-R", repo, head, "--squash", "--delete-branch"])
    if rc != 0:
        report.errors.append(f"`gh pr merge` failed: {err.strip() or out.strip()}")
        return report
    report.merged = True
    report.note = "green proof: machine-merged into integration and branch deleted."
    return report


def ship_integration(
    integration_branch: str,
    base: str = "main",
    repo: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
    prd_slug: str | None = None,
) -> ShipReport:
    """Open the integration -> main PR and STOP. The human owns this merge; this never merges."""
    run = runner or _default_runner
    report = ShipReport(mode="integration", head=integration_branch, base=base, dry_run=dry_run)

    if not INTEGRATION_BRANCH_RE.match(integration_branch):
        report.errors.append(
            f"refusing: head '{integration_branch}' is not a per-run integration "
            "branch (maestro/<slug>)."
        )
        return report
    if base not in ("main", "master"):
        report.errors.append(f"integration PR base must be main/master, got '{base}'.")
        return report

    if repo is None:
        repo, err = _resolve_repo(run)
        if err:
            report.errors.append(err)
            return report
    assert repo is not None  # _resolve_repo yields a repo string whenever err is None
    report.repo = repo

    slug = prd_slug or integration_branch.split("/", 1)[-1]
    title = f"Maestro run: integrate {slug} into {base}"
    body = (
        f"Consolidated integration PR for the Maestro run `{slug}`.\n\n"
        "All subsystem branches have been machine-merged into this integration branch on green "
        "mechanical proof (gate-3 + gate-4 + RED-lock). **This is the single human-in-the-loop "
        f"merge:** a human reviews and merges into `{base}`.\n\n"
        "> Maestro never merges to a protected branch — this PR is intentionally left for you."
    )

    if dry_run:
        report.note = "dry-run: no PR opened. (Integration PRs are never machine-merged.)"
        return report

    if not _open_pr(run, repo, integration_branch, base, title, body, report):
        return report

    report.note = (
        "integration PR opened for HUMAN review — Maestro will NOT merge it. "
        "Review and merge into main yourself."
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ship a subsystem (machine-merge on green) or open the integration PR (human merges)."""
    parser = argparse.ArgumentParser(
        description=(
            "Ship a Maestro branch by PR, enforcing the merge policy: subsystem PRs machine-merge "
            "into integration on green proof; the integration->main PR is opened but never merged."
        )
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    sp = sub.add_parser("subsystem", help="Ship a subsystem branch into the integration branch.")
    sp.add_argument(
        "--integration", required=True, help="Integration branch (maestro/<slug>), the PR base."
    )
    sp.add_argument("--subsystem", help="Subsystem name (default: derived from the branch).")
    sp.add_argument("--issue", type=int, help="Issue number (default: derived from the branch).")
    sp.add_argument("--repo", help="Target repository as org/repo (default: resolved via gh).")
    sp.add_argument(
        "--no-merge", action="store_true", help="Open the PR but do not merge, even if green."
    )
    sp.add_argument(
        "--dry-run", action="store_true", help="Report the plan/proof without any write or merge."
    )

    ip = sub.add_parser("integration", help="Open the integration->main PR (human merges).")
    ip.add_argument(
        "--integration", required=True, help="Integration branch (maestro/<slug>), the PR head."
    )
    ip.add_argument("--base", default="main", help="Base branch (default: main).")
    ip.add_argument("--repo", help="Target repository as org/repo (default: resolved via gh).")
    ip.add_argument("--dry-run", action="store_true", help="Report the plan without opening a PR.")

    args = parser.parse_args(argv)

    if args.mode == "subsystem":
        report = ship_subsystem(
            integration_branch=args.integration, subsystem=args.subsystem, issue=args.issue,
            repo=args.repo, dry_run=args.dry_run, no_merge=args.no_merge,
        )
    else:
        report = ship_integration(
            integration_branch=args.integration, base=args.base, repo=args.repo,
            dry_run=args.dry_run,
        )

    print(json.dumps(report.to_dict(), indent=2))
    for w in report.warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if not report.ok:
        print(f"ERROR: ship ({report.mode}) failed:", file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
