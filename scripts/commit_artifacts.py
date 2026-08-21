"""Gate-triggered artifact commits for Maestro's version-control integration.

At each freeze point in the `/conduct` state machine, the just-frozen documents are committed
to the per-run integration branch. This script performs that commit with a **forced shape**:
it knows exactly which files belong to each freeze point and commits *only* those, so a
subagent cannot smuggle code into a docs-freeze commit, nor "freeze" an artifact that does not
yet exist.

Freeze points (groups):
  * ``prd``          — after Phase 0 / Gate 0:   docs/PRD.md
  * ``architecture`` — after Phase 1 / Gate 0.5: docs/adr/, architecture.md, security.md,
                                                  traceability.md
  * ``spec``         — Phase 2, per subsystem:   src/modules/<subsystem>/SPEC.md + openapi.yaml
  * ``ui-spec``      — Phase 2, per UI subsystem: src/modules/<subsystem>/ui-spec.json (the
                                                  frozen UI contract from gate-ui; optional —
                                                  only for subsystems with a user interface).
  * ``tests``        — Phase 3, per subsystem:   tests/contract/<subsystem>/,
                                                  tests/behavioral/<subsystem>/, and the RED-lock
                                                  manifest .maestro/red_lock/<subsystem>.json.
                                                  This freezes the *locked* orthogonal suite on the
                                                  integration branch so every worktree cut from it
                                                  inherits the same frozen oracle. Run
                                                  ``verify_red_suite.py lock --subsystem <name>``
                                                  first — the manifest must exist before commit.

Non-negotiables enforced mechanically (exit non-zero on violation):
  * Never commit on a protected branch (``main``/``master``). A subprocess ``git commit`` here
    is NOT intercepted by the PreToolUse git gate, so this script re-enforces the rule itself.
  * Every required artifact for the group must exist — you cannot freeze what is not there.
  * The commit is scoped to the group's artifact paths only (``git commit -- <paths>``).

Command execution is injected (see ``commit_artifacts``) so the logic is unit-testable without
a real git repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Mirrors scripts.hook_git_gate.PROTECTED_BRANCHES (kept local so this file imports only stdlib
# and runs cleanly under direct `python3 scripts/commit_artifacts.py` invocation).
PROTECTED_BRANCHES = frozenset({"main", "master"})

Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]


@dataclass(frozen=True)
class Artifact:
    """A single artifact path in a freeze group, with the existence check it must satisfy."""

    path: str
    kind: str  # "file" | "adr_dir"


@dataclass
class CommitReport:
    """Outcome of an artifact commit attempt."""

    group: str
    ok: bool
    committed: bool
    branch: str | None = None
    message: str | None = None
    paths: list[str] = field(default_factory=list)
    sha: str | None = None
    missing: list[str] = field(default_factory=list)
    reason: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _artifacts_for(group: str, subsystem: str | None) -> tuple[list[Artifact], str]:
    """Return the (artifacts, commit message) for a freeze group. Raises ValueError if invalid."""
    if group == "prd":
        return [Artifact("docs/PRD.md", "file")], "docs(prd): freeze PRD [Gate 0]"
    if group == "architecture":
        artifacts = [
            Artifact("docs/architecture.md", "file"),
            Artifact("docs/security.md", "file"),
            Artifact("docs/traceability.md", "file"),
            Artifact("docs/adr", "adr_dir"),
        ]
        message = "docs(arch): freeze architecture, ADRs, security & traceability [Gate 0.5]"
        return artifacts, message
    if group == "spec":
        if not subsystem:
            raise ValueError("the 'spec' group requires --subsystem")
        base = f"src/modules/{subsystem}"
        artifacts = [
            Artifact(f"{base}/SPEC.md", "file"),
            Artifact(f"{base}/openapi.yaml", "file"),
        ]
        message = f"docs(spec): freeze {subsystem} contract [Gate 1]"
        return artifacts, message
    if group == "ui-spec":
        if not subsystem:
            raise ValueError("the 'ui-spec' group requires --subsystem")
        artifacts = [Artifact(f"src/modules/{subsystem}/ui-spec.json", "file")]
        message = f"docs(ui-spec): freeze {subsystem} UI contract [Gate UI]"
        return artifacts, message
    if group == "tests":
        if not subsystem:
            raise ValueError("the 'tests' group requires --subsystem")
        artifacts = [
            Artifact(f"tests/contract/{subsystem}", "py_dir"),
            Artifact(f"tests/behavioral/{subsystem}", "py_dir"),
            Artifact(f".maestro/red_lock/{subsystem}.json", "file"),
        ]
        message = f"test(redlock): freeze & lock {subsystem} orthogonal suite [Phase 3]"
        return artifacts, message
    raise ValueError(
        f"unknown artifact group '{group}' (expected: prd, architecture, spec, ui-spec, tests)"
    )


def _missing_artifacts(repo_root: Path, artifacts: Sequence[Artifact]) -> list[str]:
    """Return the paths of artifacts that do not satisfy their existence check."""
    missing: list[str] = []
    for art in artifacts:
        target = repo_root / art.path
        if art.kind == "adr_dir":
            if not target.is_dir() or not any(target.glob("*.md")):
                missing.append(f"{art.path} (must be a directory containing at least one ADR *.md)")
        elif art.kind == "py_dir":
            if not target.is_dir() or not any(target.glob("*.py")):
                missing.append(f"{art.path} (must be a dir containing at least one test *.py)")
        elif not target.is_file():
            missing.append(art.path)
    return missing


def _default_runner(cmd: Sequence[str]) -> tuple[int, str, str]:
    """Execute a command, returning (returncode, stdout, stderr). Never raises."""
    import subprocess

    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=60, check=False
        )
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]!r}"
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _resolve_current_branch(run: Runner, root: str) -> str | None:
    rc, out, _ = run(["git", "-C", root, "branch", "--show-current"])
    if rc != 0:
        return None
    return out.strip() or None


def commit_artifacts(
    group: str,
    subsystem: str | None = None,
    issue: int | None = None,
    repo_root: str | Path | None = None,
    dry_run: bool = False,
    runner: Runner | None = None,
    branch_resolver: Callable[[str], str | None] | None = None,
) -> CommitReport:
    """Stage and commit exactly the artifacts belonging to ``group`` on the integration branch.

    Args:
        group: One of ``prd``, ``architecture``, ``spec``, ``ui-spec``, ``tests``.
        subsystem: Required for the ``spec``, ``ui-spec``, and ``tests`` groups.
        issue: Optional GitHub issue number appended to the message as ``(#n)``.
        repo_root: Repository root; resolved via ``git rev-parse`` when omitted.
        dry_run: Validate and report the plan without staging or committing.
        runner: Injected command runner (defaults to a real subprocess runner).
        branch_resolver: Injected current-branch resolver (defaults to ``git branch``).

    Returns:
        A :class:`CommitReport`.
    """
    run = runner or _default_runner

    if repo_root is not None:
        root = Path(repo_root)
    else:
        rc, out, _ = run(["git", "rev-parse", "--show-toplevel"])
        root = Path(out.strip()) if rc == 0 and out.strip() else Path(".")

    try:
        artifacts, base_message = _artifacts_for(group, subsystem)
    except ValueError as exc:
        return CommitReport(group=group, ok=False, committed=False, reason=str(exc))

    message = f"{base_message} (#{issue})" if issue is not None else base_message
    paths = [a.path for a in artifacts]

    resolve = branch_resolver or (lambda r: _resolve_current_branch(run, r))
    branch = resolve(str(root))

    if branch in PROTECTED_BRANCHES:
        return CommitReport(
            group=group,
            ok=False,
            committed=False,
            branch=branch,
            reason=(
                f"refusing to commit artifacts on protected branch '{branch}'. Artifact commits "
                "land on the per-run integration branch (maestro/<slug>), not main."
            ),
        )

    missing = _missing_artifacts(root, artifacts)
    if missing:
        return CommitReport(
            group=group,
            ok=False,
            committed=False,
            branch=branch,
            missing=missing,
            reason=f"cannot freeze {group}: {len(missing)} required artifact(s) missing.",
        )

    if dry_run:
        return CommitReport(
            group=group, ok=True, committed=False, branch=branch,
            message=message, paths=paths, note="dry-run: nothing staged or committed",
        )

    rc, _out, err = run(["git", "-C", str(root), "add", "--", *paths])
    if rc != 0:
        return CommitReport(
            group=group, ok=False, committed=False, branch=branch, paths=paths,
            reason=f"git add failed: {err.strip()}",
        )

    # Only the artifact paths are considered — an unchanged set is an idempotent no-op (resume).
    rc, _out, _err = run(["git", "-C", str(root), "diff", "--cached", "--quiet", "--", *paths])
    if rc == 0:
        return CommitReport(
            group=group, ok=True, committed=False, branch=branch, message=message, paths=paths,
            note="nothing to commit — artifacts already frozen at this revision",
        )

    rc, _out, err = run(["git", "-C", str(root), "commit", "-m", message, "--", *paths])
    if rc != 0:
        return CommitReport(
            group=group, ok=False, committed=False, branch=branch, message=message, paths=paths,
            reason=f"git commit failed: {err.strip()}",
        )

    sha = None
    rc, out, _err = run(["git", "-C", str(root), "rev-parse", "HEAD"])
    if rc == 0:
        sha = out.strip() or None

    return CommitReport(
        group=group, ok=True, committed=True, branch=branch, message=message, paths=paths, sha=sha,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Commit a freeze group's artifacts, print a JSON report, exit non-zero on failure."""
    parser = argparse.ArgumentParser(
        description=(
            "Commit exactly the artifacts of a Maestro freeze group "
            "(prd | architecture | spec | ui-spec | tests) to the integration branch, with a "
            "forced shape and a traceable message."
        )
    )
    parser.add_argument(
        "group",
        choices=["prd", "architecture", "spec", "ui-spec", "tests"],
        help="Freeze group.",
    )
    parser.add_argument(
        "--subsystem",
        help="Subsystem name (required for the 'spec', 'ui-spec', and 'tests' groups).",
    )
    parser.add_argument("--issue", type=int, help="GitHub issue number to tag as (#n).")
    parser.add_argument("--repo-root", help="Repository root (defaults to git toplevel).")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and report the plan without committing."
    )
    args = parser.parse_args(argv)

    report = commit_artifacts(
        group=args.group,
        subsystem=args.subsystem,
        issue=args.issue,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
    )
    print(json.dumps(report.to_dict(), indent=2))

    if not report.ok:
        print(f"ERROR: {report.reason}", file=sys.stderr)
        for m in report.missing:
            print(f"  - missing: {m}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
