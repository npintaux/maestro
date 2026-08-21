"""Manage per-subsystem git worktrees for Maestro's parallel implementation phase.

After the RED suite is locked on the per-run integration branch (``maestro/<slug>``), each
subsystem is implemented in parallel. This gives each implementer its own **git worktree** under
``.maestro/worktrees/<subsystem>/`` checked out on its own ``issue/<n>-<slug>`` branch, cut from
the integration branch. That is *git-level* isolation — it complements, and does not replace, the
PreToolUse boundary guard's *path-level* isolation (an implementer may only write inside its own
subsystem's paths). Two orthogonal fences around the same subsystem.

Non-negotiables enforced mechanically (exit non-zero on violation):
  * Worktrees are cut from the **integration branch** only. A base of ``main``/``master`` (or any
    non-``maestro/<slug>`` branch) is refused — the no-commit-to-main invariant starts here.
  * Every branch name is built as ``issue/<n>-<slug>`` (snake->kebab slug, the single mapping
    shared with create_subsystem_issues) and validated against the git gate's subsystem-branch
    shape before any worktree is created.
  * Creation never clobbers: a path already occupied by a *different* branch, or by a non-worktree
    directory, is an error, not an overwrite. An already-correct worktree is an idempotent no-op
    (resume-safe).

Command execution is injected so the logic is unit-testable without a real repo; ``--dry-run``
reports the plan without touching git.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# One parsed `git worktree list --porcelain` entry, and a create spec ({subsystem, issue}).
WorktreeEntry = dict[str, str | None]
Spec = dict[str, Any]

try:
    from scripts.create_subsystem_issues import _branch_slug
    from scripts.hook_git_gate import (
        INTEGRATION_BRANCH_RE,
        PROTECTED_BRANCHES,
        SUBSYSTEM_BRANCH_RE,
    )
except ImportError:  # pragma: no cover - direct-invocation bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.create_subsystem_issues import _branch_slug
    from scripts.hook_git_gate import (
        INTEGRATION_BRANCH_RE,
        PROTECTED_BRANCHES,
        SUBSYSTEM_BRANCH_RE,
    )

Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]

WORKTREE_SUBDIR = ".maestro/worktrees"


@dataclass
class WorktreeAction:
    """A single create/skip/remove outcome."""

    subsystem: str
    action: str  # "create" | "skip" | "remove" | "plan"
    path: str | None = None
    branch: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class WorktreeReport:
    """Outcome of a worktree operation."""

    command: str
    integration: str | None = None
    root: str | None = None
    dry_run: bool = False
    created: list[WorktreeAction] = field(default_factory=list)
    skipped: list[WorktreeAction] = field(default_factory=list)
    removed: list[WorktreeAction] = field(default_factory=list)
    listed: list[dict[str, str | None]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "command": self.command,
            "integration": self.integration,
            "root": self.root,
            "dry_run": self.dry_run,
            "created": [a.to_dict() for a in self.created],
            "skipped": [a.to_dict() for a in self.skipped],
            "removed": [a.to_dict() for a in self.removed],
            "listed": self.listed,
            "warnings": self.warnings,
            "errors": self.errors,
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


def _repo_root(run: Runner, override: str | None) -> Path:
    if override:
        return Path(override)
    rc, out, _ = run(["git", "rev-parse", "--show-toplevel"])
    return Path(out.strip()) if rc == 0 and out.strip() else Path(".")


def _parse_worktrees(porcelain: str) -> dict[str, WorktreeEntry]:
    """Parse ``git worktree list --porcelain`` into {abs_path: {'branch', 'head'}}."""
    result: dict[str, WorktreeEntry] = {}
    path: str | None = None
    entry: WorktreeEntry = {}
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            if path is not None:
                result[path] = entry
            path = line[len("worktree "):].strip()
            entry = {"branch": None, "head": None}
        elif line.startswith("HEAD "):
            entry["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            entry["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    if path is not None:
        result[path] = entry
    return result


def _existing_worktrees(run: Runner) -> dict[str, WorktreeEntry]:
    rc, out, _ = run(["git", "worktree", "list", "--porcelain"])
    return _parse_worktrees(out) if rc == 0 else {}


def _branch_exists(run: Runner, branch: str) -> bool:
    rc, _out, _err = run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])
    return rc == 0


def _worktree_path(root: Path, subsystem: str) -> Path:
    return root / WORKTREE_SUBDIR / subsystem


def _validate_integration(integration: str, report: WorktreeReport) -> bool:
    if integration in PROTECTED_BRANCHES or not INTEGRATION_BRANCH_RE.match(integration):
        report.errors.append(
            f"refusing: worktrees are cut from a per-run integration branch (maestro/<slug>), "
            f"not '{integration}'. Never branch subsystem work off main/master."
        )
        return False
    return True


def create_worktrees(
    integration: str,
    specs: Sequence[Spec],
    repo_root: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
) -> WorktreeReport:
    """Create one ``issue/<n>-<slug>`` worktree per spec ({subsystem, issue}) off integration."""
    run = runner or _default_runner
    report = WorktreeReport(command="create", integration=integration, dry_run=dry_run)

    if not _validate_integration(integration, report):
        return report
    if not specs:
        report.errors.append("no subsystems given; nothing to create.")
        return report

    root = _repo_root(run, repo_root)
    report.root = str(root)
    existing = _existing_worktrees(run)

    for spec in specs:
        subsystem = str(spec.get("subsystem", "")).strip()
        issue = spec.get("issue")
        if not subsystem or issue is None:
            report.errors.append(f"invalid spec (need 'subsystem' and 'issue'): {spec!r}")
            continue

        slug = _branch_slug(subsystem)
        branch = f"issue/{issue}-{slug}"
        if not SUBSYSTEM_BRANCH_RE.match(branch):
            report.errors.append(
                f"refusing: computed branch '{branch}' for subsystem '{subsystem}' is not a valid "
                "subsystem-branch shape (issue/<n>-<slug>)."
            )
            continue

        path = _worktree_path(root, subsystem)
        path_str = str(path)
        rel = f"{WORKTREE_SUBDIR}/{subsystem}"

        # Idempotency / no-clobber.
        registered = existing.get(path_str)
        if registered is not None:
            if registered.get("branch") == branch:
                report.skipped.append(
                    WorktreeAction(
                        subsystem, "skip", rel, branch,
                        "worktree already present on the right branch",
                    )
                )
            else:
                report.errors.append(
                    f"path '{rel}' is already a worktree on branch '{registered.get('branch')}', "
                    f"not '{branch}'; refusing to clobber."
                )
            continue
        if path.exists():
            report.errors.append(
                f"path '{rel}' exists but is not a registered git worktree; refusing to clobber."
            )
            continue

        if dry_run:
            report.created.append(WorktreeAction(subsystem, "plan", rel, branch, "dry-run"))
            continue

        if _branch_exists(run, branch):
            cmd = ["git", "worktree", "add", path_str, branch]
        else:
            cmd = ["git", "worktree", "add", "-b", branch, path_str, integration]
        rc, _out, err = run(cmd)
        if rc != 0:
            report.errors.append(f"`git worktree add` failed for '{subsystem}': {err.strip()}")
            continue
        report.created.append(WorktreeAction(subsystem, "create", rel, branch))

    return report


def list_worktrees(
    repo_root: str | None = None, runner: Runner | None = None
) -> WorktreeReport:
    """List the Maestro worktrees (those under .maestro/worktrees/)."""
    run = runner or _default_runner
    report = WorktreeReport(command="list")
    root = _repo_root(run, repo_root)
    report.root = str(root)
    marker = f"/{WORKTREE_SUBDIR}/"
    for path, entry in _existing_worktrees(run).items():
        if marker in path.replace("\\", "/"):
            report.listed.append(
                {"path": path, "branch": entry.get("branch"), "head": entry.get("head")}
            )
    return report


def _remove_one(
    run: Runner, path: Path, subsystem: str, force: bool, report: WorktreeReport
) -> None:
    path_str = str(path)
    rel = f"{WORKTREE_SUBDIR}/{subsystem}"
    cmd = ["git", "worktree", "remove", path_str]
    if force:
        cmd.append("--force")
    rc, _out, err = run(cmd)
    if rc != 0:
        report.errors.append(
            f"`git worktree remove` failed for '{subsystem}': {err.strip()} "
            "(uncommitted work? re-run with --force to discard)."
        )
        return
    report.removed.append(WorktreeAction(subsystem, "remove", rel))


def remove_worktree(
    subsystem: str,
    repo_root: str | None = None,
    runner: Runner | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> WorktreeReport:
    """Remove a single subsystem's worktree (idempotent if it is already gone)."""
    run = runner or _default_runner
    report = WorktreeReport(command="remove", dry_run=dry_run)
    root = _repo_root(run, repo_root)
    report.root = str(root)
    path = _worktree_path(root, subsystem)
    rel = f"{WORKTREE_SUBDIR}/{subsystem}"

    if str(path) not in _existing_worktrees(run):
        report.skipped.append(
            WorktreeAction(subsystem, "skip", rel, reason="not a registered worktree")
        )
        return report
    if dry_run:
        report.removed.append(WorktreeAction(subsystem, "plan", rel, reason="dry-run"))
        return report
    _remove_one(run, path, subsystem, force, report)
    return report


def teardown(
    repo_root: str | None = None,
    runner: Runner | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> WorktreeReport:
    """Remove ALL Maestro worktrees (end-of-run cleanup). Branches are left intact."""
    run = runner or _default_runner
    report = WorktreeReport(command="teardown", dry_run=dry_run)
    root = _repo_root(run, repo_root)
    report.root = str(root)
    marker = f"/{WORKTREE_SUBDIR}/"
    for path, _entry in _existing_worktrees(run).items():
        norm = path.replace("\\", "/")
        if marker not in norm:
            continue
        subsystem = norm.rsplit("/", 1)[-1]
        rel = f"{WORKTREE_SUBDIR}/{subsystem}"
        if dry_run:
            report.removed.append(WorktreeAction(subsystem, "plan", rel, reason="dry-run"))
            continue
        _remove_one(run, Path(path), subsystem, force, report)
    return report


def _load_specs(args: argparse.Namespace) -> tuple[list[Spec], str | None]:
    """Build the create specs from --spec JSON or a single --subsystem/--issue pair."""
    if args.spec:
        try:
            data = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], f"could not read --spec '{args.spec}': {exc}"
        if not isinstance(data, list):
            return [], "--spec must be a JSON array of {subsystem, issue} objects."
        return data, None
    if args.subsystem and args.issue is not None:
        return [{"subsystem": args.subsystem, "issue": args.issue}], None
    return [], "provide either --spec <file.json> or both --subsystem and --issue."


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: create/list/remove/teardown Maestro subsystem worktrees."""
    parser = argparse.ArgumentParser(
        description="Manage per-subsystem git worktrees (.maestro/worktrees/<subsystem>/) cut from "
        "the per-run integration branch."
    )
    parser.add_argument("--repo-root", help="Repository root (defaults to git toplevel).")
    sub = parser.add_subparsers(dest="command", required=True)

    cp = sub.add_parser("create", help="Create worktrees cut from the integration branch.")
    cp.add_argument("--integration", required=True, help="Integration branch (maestro/<slug>).")
    cp.add_argument("--subsystem", help="Single subsystem name.")
    cp.add_argument("--issue", type=int, help="Issue number for the single subsystem.")
    cp.add_argument("--spec", help="JSON array of {subsystem, issue} for batch creation.")
    cp.add_argument("--dry-run", action="store_true", help="Report the plan without touching git.")

    sub.add_parser("list", help="List Maestro worktrees.")

    rp = sub.add_parser("remove", help="Remove one subsystem's worktree.")
    rp.add_argument("--subsystem", required=True, help="Subsystem whose worktree to remove.")
    rp.add_argument("--force", action="store_true", help="Discard uncommitted work in worktree.")
    rp.add_argument("--dry-run", action="store_true", help="Report the plan without touching git.")

    tp = sub.add_parser("teardown", help="Remove all Maestro worktrees (branches kept).")
    tp.add_argument("--force", action="store_true", help="Discard uncommitted work in worktrees.")
    tp.add_argument("--dry-run", action="store_true", help="Report the plan without touching git.")

    args = parser.parse_args(argv)

    if args.command == "create":
        specs, err = _load_specs(args)
        if err:
            report = WorktreeReport(command="create", integration=args.integration)
            report.errors.append(err)
        else:
            report = create_worktrees(
                args.integration, specs, repo_root=args.repo_root, dry_run=args.dry_run
            )
    elif args.command == "list":
        report = list_worktrees(repo_root=args.repo_root)
    elif args.command == "remove":
        report = remove_worktree(
            args.subsystem, repo_root=args.repo_root, force=args.force, dry_run=args.dry_run
        )
    else:  # teardown
        report = teardown(repo_root=args.repo_root, force=args.force, dry_run=args.dry_run)

    print(json.dumps(report.to_dict(), indent=2))
    for w in report.warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if not report.ok:
        print(f"ERROR: worktree {report.command} failed:", file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
