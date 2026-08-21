"""Create the ``type:subsystem`` tracking issues from the traceability matrix.

Product stories (``type:story``, born from the PRD via ``prd-to-backlog``) and technical
subsystems are orthogonal axes bridged by ``docs/traceability.md`` (see audit_traceability.py).
Once that matrix has passed its coverage gate, this step turns the *technical* axis into GitHub
issues: **one ``type:subsystem`` tracking issue per subsystem**, each cross-linking upward to the
story issues it serves. Those issue numbers are what the branch names ``issue/<n>-<subsystem>``
are built from, so this step runs at the Gate 0.5 -> Phase 2 handoff, before any subsystem branch
or worktree exists.

Everything here goes through the ``gh`` CLI, per the Antigravity ``permissioned-github`` contract
(``gh -R <org>/<repo> …``; no ``curl``, no direct API). Command execution is injected so the logic
is unit-testable without touching a real repository, and ``--dry-run`` reports the plan (still
validating that every served story already has a GitHub issue) without any write.

Non-negotiables enforced mechanically (exit non-zero on violation):
  * Every subsystem in the matrix must serve at least one story whose GitHub **story issue already
    exists**. A subsystem issue is never created with a broken/absent story link — that would be a
    silent traceability hole, so it fails loudly instead.
  * Reconciliation is idempotent, keyed on a hidden ``maestro-subsystem`` marker (mirroring
    ``prd-to-backlog``'s ``prd-sync`` approach): existing issues are updated only when their body
    changed, and never duplicated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# A GitHub issue as returned by `gh issue list --json …` — string keys, heterogeneous values.
IssueDict = dict[str, Any]

# Reuse the *exact* matrix parser the coverage gate uses, so the creator and the gate can never
# disagree about what the traceability table says. Fall back to a path bootstrap for direct
# ``python3 scripts/create_subsystem_issues.py`` invocation (where ``scripts`` is not yet a package
# on sys.path).
try:
    from scripts.audit_traceability import _parse_matrix
except ImportError:  # pragma: no cover - direct-invocation bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.audit_traceability import _parse_matrix

Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]

SUBSYSTEM_LABEL = "type:subsystem"

# Hidden reconciliation marker stamped into every subsystem issue we create — the load-bearing
# identity, matched on re-runs so issues are updated, not duplicated.
SUBSYSTEM_MARKER_RE = re.compile(r"maestro-subsystem:\s*name=([A-Za-z0-9_\-]+)")

# Story-issue identity, recovered from the prd-sync marker prd-to-backlog stamps, falling back to
# the ``[USn]`` title key for issues created before markers existed (same tolerance as that skill).
STORY_MARKER_RE = re.compile(r"prd-sync:\s*key=us(\d+)", re.IGNORECASE)
STORY_TITLE_RE = re.compile(r"\[US-?(\d+)\]", re.IGNORECASE)

# Pull the issue number out of the URL `gh issue create` prints on stdout.
_ISSUE_URL_RE = re.compile(r"/issues/(\d+)")


def _branch_slug(subsystem: str) -> str:
    """Slugify a subsystem name for use in a branch suffix.

    Subsystem directories are snake_case (``src/modules/redirect_resolver``) but the git gate's
    subsystem-branch shape is kebab-only (``^issue/[0-9]+-[a-z0-9-]+$``), so underscores become
    hyphens here. This is the single definition of that mapping.
    """
    return subsystem.strip().lower().replace("_", "-")


@dataclass
class SubsystemPlan:
    """The intended issue for one subsystem, after resolving its story links."""

    subsystem: str
    stories: list[str] = field(default_factory=list)  # normalized US-N, sorted
    story_issues: dict[str, int] = field(default_factory=dict)  # US-N -> story issue number
    title: str = ""
    body: str = ""
    branch_slug: str = ""


@dataclass
class IssueOutcome:
    """What happened (or would happen) for one subsystem issue."""

    subsystem: str
    action: str  # "create" | "update" | "skip"
    number: int | None = None
    title: str | None = None
    stories: list[str] = field(default_factory=list)
    branch_slug: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ReconcileReport:
    """Outcome of reconciling subsystem tracking issues against the matrix."""

    repo: str | None = None
    dry_run: bool = False
    created: list[IssueOutcome] = field(default_factory=list)
    updated: list[IssueOutcome] = field(default_factory=list)
    skipped: list[IssueOutcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "repo": self.repo,
            "dry_run": self.dry_run,
            "created": [o.to_dict() for o in self.created],
            "updated": [o.to_dict() for o in self.updated],
            "skipped": [o.to_dict() for o in self.skipped],
            "warnings": self.warnings,
            "errors": self.errors,
        }


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


def _invert_matrix(mapping: dict[str, set[str]]) -> dict[str, list[str]]:
    """Turn ``{US-N: {subsystems}}`` into ``{subsystem: [sorted US-N]}``."""
    inverted: dict[str, set[str]] = {}
    for story, subs in mapping.items():
        for sub in subs:
            inverted.setdefault(sub, set()).add(story)
    return {sub: sorted(stories) for sub, stories in inverted.items()}


def _story_issue_map(issues: Sequence[IssueDict]) -> dict[str, int]:
    """Map ``US-N`` -> story issue number, from the prd-sync marker or the title key."""
    mapping: dict[str, int] = {}
    for issue in issues:
        number = issue.get("number")
        if not isinstance(number, int):
            continue
        body = issue.get("body") or ""
        title = issue.get("title") or ""
        match = STORY_MARKER_RE.search(body) or STORY_TITLE_RE.search(title)
        if match:
            mapping[f"US-{int(match.group(1))}"] = number
    return mapping


def _existing_subsystem_issues(issues: Sequence[IssueDict]) -> dict[str, IssueDict]:
    """Map subsystem name -> the existing tracking issue (by its maestro-subsystem marker)."""
    mapping: dict[str, IssueDict] = {}
    for issue in issues:
        body = issue.get("body") or ""
        match = SUBSYSTEM_MARKER_RE.search(body)
        if match and isinstance(issue.get("number"), int):
            mapping[match.group(1)] = issue
    return mapping


def _render_body(subsystem: str, stories: Sequence[str], story_issues: dict[str, int]) -> str:
    """Render the subsystem tracking issue body, with the hidden marker and story cross-links."""
    slug = _branch_slug(subsystem)
    lines = [
        f"<!-- maestro-subsystem: name={subsystem} -->",
        "",
        "**Type:** subsystem tracking issue (engineering-owned)",
        "",
        "Implements the following product stories:",
    ]
    lines += [f"- {story} (#{story_issues[story]})" for story in stories]
    lines += [
        "",
        f"**Branch slug:** `{slug}` — the implementation branch will be "
        f"`issue/<this-issue-number>-{slug}`, cut from the per-run integration branch in Phase 3.",
        "",
        "The Tech Lead for this subsystem may open sub-issues under this tracking issue for finer "
        "decomposition (per-endpoint, per-pattern-slice).",
    ]
    return "\n".join(lines)


def _list_issues(run: Runner, repo: str) -> tuple[list[IssueDict] | None, str | None]:
    """Fetch all issues (open + closed) with the fields we reconcile on."""
    rc, out, err = run(
        ["gh", "issue", "list", "-R", repo, "--state", "all", "--limit", "1000",
         "--json", "number,title,body"]
    )
    if rc != 0:
        return None, f"`gh issue list` failed: {err.strip() or out.strip()}"
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        return None, f"could not parse `gh issue list` output as JSON: {exc}"
    if not isinstance(data, list):
        return None, "unexpected `gh issue list` output (expected a JSON array)"
    return data, None


def _resolve_repo(run: Runner) -> tuple[str | None, str | None]:
    """Resolve the ``org/repo`` slug via ``gh repo view`` when not supplied explicitly."""
    rc, out, err = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if rc != 0 or not out.strip():
        detail = err.strip() or out.strip()
        return None, f"could not resolve repository via `gh repo view`: {detail}"
    return out.strip(), None


def reconcile_subsystem_issues(
    matrix_text: str,
    repo: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
    ensure_label: bool = True,
) -> ReconcileReport:
    """Create/update one ``type:subsystem`` tracking issue per subsystem in the matrix.

    Args:
        matrix_text: Contents of ``docs/traceability.md`` (parsed with the coverage gate's parser).
        repo: ``org/repo`` slug; resolved via ``gh repo view`` when omitted.
        runner: Injected command runner (defaults to a real subprocess runner).
        dry_run: Report the plan (and still fail on missing story issues) without any write.
        ensure_label: Best-effort create the ``type:subsystem`` label before creating issues.

    Returns:
        A :class:`ReconcileReport`; ``report.ok`` is false (``main`` exits non-zero) on any error.
    """
    run = runner or _default_runner
    report = ReconcileReport(dry_run=dry_run)

    if repo is None:
        repo, err = _resolve_repo(run)
        if err:
            report.errors.append(err)
            return report
    assert repo is not None  # _resolve_repo yields a repo string whenever err is None
    report.repo = repo

    inverted = _invert_matrix(_parse_matrix(matrix_text))
    if not inverted:
        report.errors.append(
            "docs/traceability.md yields no subsystems; nothing to create "
            "(did the traceability gate pass first?)."
        )
        return report

    issues, err = _list_issues(run, repo)
    if err:
        report.errors.append(err)
        return report
    assert issues is not None  # _list_issues yields a list whenever err is None

    story_issues = _story_issue_map(issues)
    existing = _existing_subsystem_issues(issues)

    # Resolve story links first; a subsystem whose stories have no GitHub issue is a hard error.
    plans: list[SubsystemPlan] = []
    for subsystem in sorted(inverted):
        stories = inverted[subsystem]
        missing = [s for s in stories if s not in story_issues]
        if missing:
            report.errors.append(
                f"subsystem '{subsystem}' serves {', '.join(missing)} but no GitHub story issue "
                "exists for those stories (run prd-to-backlog before creating subsystem issues)."
            )
            continue
        resolved = {s: story_issues[s] for s in stories}
        plans.append(
            SubsystemPlan(
                subsystem=subsystem,
                stories=stories,
                story_issues=resolved,
                title=f"[subsystem] {subsystem}",
                body=_render_body(subsystem, stories, resolved),
                branch_slug=_branch_slug(subsystem),
            )
        )

    if report.errors:
        # Fail before mutating anything — do not create half a backlog with dangling links.
        return report

    if ensure_label and not dry_run:
        rc, _out, err = run(
            ["gh", "label", "create", SUBSYSTEM_LABEL, "-R", repo, "--color", "BFD4F2",
             "--description", "Subsystem tracking issue (engineering-owned)", "--force"]
        )
        if rc != 0:
            report.warnings.append(
                f"could not ensure the '{SUBSYSTEM_LABEL}' label exists (continuing): "
                f"{err.strip()}"
            )

    for plan in plans:
        current = existing.get(plan.subsystem)
        if current is None:
            _apply_create(run, repo, plan, report, dry_run)
        elif (current.get("body") or "").strip() != plan.body.strip():
            _apply_update(run, repo, plan, current, report, dry_run)
        else:
            report.skipped.append(
                IssueOutcome(
                    subsystem=plan.subsystem, action="skip", number=current.get("number"),
                    title=plan.title, stories=plan.stories, branch_slug=plan.branch_slug,
                    reason="already up to date",
                )
            )

    return report


def _apply_create(
    run: Runner, repo: str, plan: SubsystemPlan, report: ReconcileReport, dry_run: bool
) -> None:
    if dry_run:
        report.created.append(
            IssueOutcome(
                subsystem=plan.subsystem, action="create", title=plan.title,
                stories=plan.stories, branch_slug=plan.branch_slug, reason="dry-run",
            )
        )
        return
    rc, out, err = run(
        ["gh", "issue", "create", "-R", repo, "--title", plan.title, "--body", plan.body,
         "--label", SUBSYSTEM_LABEL]
    )
    if rc != 0:
        detail = err.strip() or out.strip()
        report.errors.append(f"`gh issue create` failed for '{plan.subsystem}': {detail}")
        return
    match = _ISSUE_URL_RE.search(out)
    number = int(match.group(1)) if match else None
    report.created.append(
        IssueOutcome(
            subsystem=plan.subsystem, action="create", number=number, title=plan.title,
            stories=plan.stories, branch_slug=plan.branch_slug,
        )
    )


def _apply_update(
    run: Runner, repo: str, plan: SubsystemPlan, current: IssueDict,
    report: ReconcileReport, dry_run: bool,
) -> None:
    number = current.get("number")
    if dry_run:
        report.updated.append(
            IssueOutcome(
                subsystem=plan.subsystem, action="update", number=number, title=plan.title,
                stories=plan.stories, branch_slug=plan.branch_slug, reason="dry-run",
            )
        )
        return
    rc, out, err = run(
        ["gh", "issue", "edit", str(number), "-R", repo, "--body", plan.body]
    )
    if rc != 0:
        detail = err.strip() or out.strip()
        report.errors.append(f"`gh issue edit` failed for '{plan.subsystem}' (#{number}): {detail}")
        return
    report.updated.append(
        IssueOutcome(
            subsystem=plan.subsystem, action="update", number=number, title=plan.title,
            stories=plan.stories, branch_slug=plan.branch_slug,
        )
    )


def reconcile_file(
    traceability: Path,
    repo: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
    ensure_label: bool = True,
) -> ReconcileReport:
    """Read the traceability matrix from disk and reconcile. Missing file is a clear error."""
    if not traceability.is_file():
        report = ReconcileReport(repo=repo, dry_run=dry_run)
        report.errors.append(f"required input missing: {traceability}")
        return report
    return reconcile_subsystem_issues(
        traceability.read_text(encoding="utf-8"),
        repo=repo,
        runner=runner,
        dry_run=dry_run,
        ensure_label=ensure_label,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Reconcile subsystem issues, print a JSON report, exit non-zero on any error."""
    parser = argparse.ArgumentParser(
        description=(
            "Create one type:subsystem tracking issue per subsystem in docs/traceability.md, "
            "cross-linked to the story issues it serves (via gh)."
        )
    )
    parser.add_argument(
        "--traceability",
        default="docs/traceability.md",
        help="Path to the traceability matrix (default: docs/traceability.md).",
    )
    parser.add_argument("--repo", help="Target repository as org/repo (default: resolved via gh).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report the plan (still failing on missing story issues) without any write.",
    )
    parser.add_argument(
        "--no-label", action="store_true",
        help="Do not attempt to ensure the type:subsystem label exists.",
    )
    args = parser.parse_args(argv)

    report = reconcile_file(
        Path(args.traceability),
        repo=args.repo,
        dry_run=args.dry_run,
        ensure_label=not args.no_label,
    )
    print(json.dumps(report.to_dict(), indent=2))

    for w in report.warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not report.ok:
        print(f"ERROR: subsystem-issue reconciliation failed with {len(report.errors)} error(s):",
              file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
