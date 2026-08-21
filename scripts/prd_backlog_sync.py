"""Reconcile the PRD's user stories into GitHub ``type:story`` issues (via ``gh``).

This is the Maestro port of the SDD ``prd-to-backlog`` skill. The original leaves the whole
job — parsing story keys, hashing PRD sections, reading markers, deciding create/update/skip,
and issuing the GitHub MCP calls — to the model under task pressure, i.e. to prose. Under the
Maestro thesis that does not bite, so the load-bearing part is a **script**: identity, change
detection, reconciliation, and every ``gh`` mutation are deterministic here, and only the
authoring of the story text stays upstream (in ``prd-validate``, which freezes ``docs/PRD.md``
with structured ``US-N`` stories and Given/When/Then acceptance criteria).

Because the PRD is already the frozen source of truth, this sync needs no creative drafting:
each story's issue body is rendered mechanically from its PRD section, and the reconciliation
marker's ``src-sha`` is a hash of that **PRD section** (never of the drafted body — the source
hash is stable run to run, the wording is not).

Reconciliation (keyed on the story ``key``, mirroring prd-to-backlog / create_subsystem_issues):
  * **New**       — no issue for this ``us<n>``       -> create (type:story + status:draft).
  * **Changed**   — issue exists, ``src-sha`` differs -> update the body (refresh src-sha).
  * **Unchanged** — issue exists, ``src-sha`` matches -> skip (no write).
  * **Removed**   — issue exists, key gone from PRD   -> left intact, flagged (never closed).

Non-negotiables enforced mechanically (exit non-zero on violation):
  * The PRD must exist and declare at least one User Story.
  * Any ``gh`` create/edit/list failure is a hard error (no half-synced, duplicated backlog).
Everything goes through ``gh -R <org>/<repo> …`` per the ``permissioned-github`` contract;
command execution is injected for testing, and ``--dry-run`` reports the plan without any write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]

# A GitHub issue as returned by `gh issue list --json …` — string keys, heterogeneous values.
IssueDict = dict[str, Any]

STORY_LABEL = "type:story"
DRAFT_LABEL = "status:draft"

# A heading that names a User Story, tolerant of `#### Story US-1: X`, `# [US1] X`, `## US-1 — X`
# (case-insensitive; hyphen/space/none between US and the number), matching prd-to-backlog's
# "liberal on input" rule. Normalized identity is always us<n>.
STORY_HEADING_RE = re.compile(
    r"^#{1,6}\s+.*?\bUS[\s\-]?(?P<n>\d+)\b\s*[:.\]]?\s*(?P<title>.*)$", re.IGNORECASE
)
# Any markdown heading or horizontal rule — the boundary that ends a story's section.
_BOUNDARY_RE = re.compile(r"^(#{1,6}\s|-{3,}\s*$)")

# Story-issue identity recovered from an existing issue: the prd-sync marker (authoritative,
# carries src-sha), falling back to the [USn] title key (sha unknown -> treated as changed).
_MARKER_RE = re.compile(
    r"prd-sync:\s*key=us(?P<n>\d+)(?:\s+src-sha=(?P<sha>[0-9a-f]+))?", re.IGNORECASE
)
_TITLE_KEY_RE = re.compile(r"\[US-?(?P<n>\d+)\]", re.IGNORECASE)

_ISSUE_URL_RE = re.compile(r"/issues/(\d+)")

# MoSCoW priority derivation (derive, don't demand). Ordered most- to least-important so the
# strongest signal in a story's text wins; absence yields no priority label (a note, not a failure).
_PRIORITY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("must-have", re.compile(r"\b(must[\s-]?have|must|critical|required)\b", re.IGNORECASE)),
    ("should-have", re.compile(r"\b(should[\s-]?have|should)\b", re.IGNORECASE)),
    ("could-have",
     re.compile(r"\b(could[\s-]?have|could|nice[\s-]?to[\s-]?have|stretch)\b", re.IGNORECASE)),
    ("wont-have", re.compile(r"\b(won'?t[\s-]?have|will not have|out of scope)\b", re.IGNORECASE)),
)


@dataclass
class Story:
    """One PRD user story, mechanically extracted from ``docs/PRD.md`` Section 5."""

    n: int
    title: str
    section: str  # the story's PRD text (title + body), the exact source the issue derives from
    src_sha: str
    priority: str | None = None

    @property
    def key(self) -> str:
        return f"us{self.n}"

    @property
    def issue_title(self) -> str:
        title = self.title.strip() or "(untitled)"
        return f"[US{self.n}] {title}"


@dataclass
class StoryOutcome:
    """What happened (or would happen) for one story."""

    key: str
    action: str  # "create" | "update" | "skip" | "removed"
    number: int | None = None
    title: str | None = None
    priority: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class BacklogReport:
    """Outcome of reconciling the PRD's user stories into GitHub issues."""

    repo: str | None = None
    dry_run: bool = False
    created: list[StoryOutcome] = field(default_factory=list)
    updated: list[StoryOutcome] = field(default_factory=list)
    skipped: list[StoryOutcome] = field(default_factory=list)
    removed: list[StoryOutcome] = field(default_factory=list)
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
            "removed": [o.to_dict() for o in self.removed],
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


def _src_sha(section: str) -> str:
    """Short, stable hash of a story's PRD section — the change-detection key."""
    normalized = "\n".join(line.rstrip() for line in section.strip().splitlines())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _derive_priority(section: str) -> str | None:
    """Derive a MoSCoW priority label from the story text, or None if the PRD doesn't signal one."""
    for label, pattern in _PRIORITY_RULES:
        if pattern.search(section):
            return label
    return None


def _parse_prd_stories(prd_text: str) -> tuple[list[Story], list[str]]:
    """Extract user stories from the PRD. Returns (stories, warnings)."""
    lines = prd_text.splitlines()
    stories: list[Story] = []
    seen: set[int] = set()
    warnings: list[str] = []

    i = 0
    while i < len(lines):
        m = STORY_HEADING_RE.match(lines[i])
        if not m:
            i += 1
            continue
        n = int(m.group("n"))
        title = m.group("title").strip().strip("[]").strip()

        body: list[str] = []
        j = i + 1
        while j < len(lines) and not _BOUNDARY_RE.match(lines[j]):
            body.append(lines[j])
            j += 1

        section = (lines[i].strip() + "\n" + "\n".join(body)).strip()

        if n in seen:
            warnings.append(f"duplicate story heading US-{n} in PRD; keeping the first occurrence.")
        else:
            seen.add(n)
            stories.append(
                Story(
                    n=n,
                    title=title,
                    section=section,
                    src_sha=_src_sha(section),
                    priority=_derive_priority(section),
                )
            )
        i = j
    stories.sort(key=lambda s: s.n)
    return stories, warnings


def _render_body(story: Story) -> str:
    """Render an issue body: the hidden marker, the PRD story text, and a PRD source link."""
    lines = [
        f"<!-- prd-sync: key={story.key} src-sha={story.src_sha} -->",
        f"# {story.issue_title}",
        "",
    ]
    # The PRD section, minus its own heading line (the first line), which the title already carries.
    section_body = "\n".join(story.section.splitlines()[1:]).strip()
    if section_body:
        lines += [section_body, ""]
    lines += [
        "---",
        f"**PRD Source:** [docs/PRD.md](docs/PRD.md) — story US-{story.n}.",
        "",
        "_Drafted by Maestro from the frozen PRD. Priority and draft state are GitHub labels, "
        "not body text; the Product Owner publishes by removing the `status:draft` label._",
    ]
    return "\n".join(lines)


def _list_issues(run: Runner, repo: str) -> tuple[list[IssueDict] | None, str | None]:
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


def _existing_story_issues(issues: Sequence[IssueDict]) -> dict[int, IssueDict]:
    """Map story number -> {'number', 'sha'} from existing issues (marker first, title fallback)."""
    mapping: dict[int, IssueDict] = {}
    for issue in issues:
        number = issue.get("number")
        if not isinstance(number, int):
            continue
        body = issue.get("body") or ""
        title = issue.get("title") or ""
        marker = _MARKER_RE.search(body)
        if marker:
            n = int(marker.group("n"))
            mapping[n] = {"number": number, "sha": (marker.group("sha") or "").lower() or None}
            continue
        title_key = _TITLE_KEY_RE.search(title)
        if title_key:
            n = int(title_key.group("n"))
            # No stored sha -> unknown -> forces an update so the marker gets stamped.
            mapping.setdefault(n, {"number": number, "sha": None})
    return mapping


def _resolve_repo(run: Runner) -> tuple[str | None, str | None]:
    rc, out, err = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if rc != 0 or not out.strip():
        detail = err.strip() or out.strip()
        return None, f"could not resolve repository via `gh repo view`: {detail}"
    return out.strip(), None


def _ensure_label(run: Runner, repo: str, name: str, color: str, desc: str) -> str | None:
    rc, _out, err = run(
        ["gh", "label", "create", name, "-R", repo,
         "--color", color, "--description", desc, "--force"]
    )
    if rc != 0:
        return f"could not ensure the '{name}' label exists (continuing): {err.strip()}"
    return None


def reconcile_backlog(
    prd_text: str,
    repo: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
    ensure_label: bool = True,
) -> BacklogReport:
    """Reconcile PRD user stories into GitHub ``type:story`` issues. See module docstring."""
    run = runner or _default_runner
    report = BacklogReport(dry_run=dry_run)

    if repo is None:
        repo, err = _resolve_repo(run)
        if err:
            report.errors.append(err)
            return report
    assert repo is not None  # _resolve_repo yields a repo string whenever err is None
    report.repo = repo

    stories, parse_warnings = _parse_prd_stories(prd_text)
    report.warnings.extend(parse_warnings)
    if not stories:
        report.errors.append(
            "docs/PRD.md declares no User Stories (US-N headings in Section 5); nothing to sync."
        )
        return report

    issues, err = _list_issues(run, repo)
    if err:
        report.errors.append(err)
        return report
    assert issues is not None  # _list_issues yields a list whenever err is None
    existing = _existing_story_issues(issues)

    # Ensure the labels we apply exist (best-effort; failures are warnings, not fatal).
    if ensure_label and not dry_run:
        wanted = {STORY_LABEL: "0e8a16", DRAFT_LABEL: "fbca04"}
        for s in stories:
            if s.priority:
                wanted.setdefault(s.priority, "5319e7")
        for name, color in wanted.items():
            w = _ensure_label(run, repo, name, color, "Maestro backlog label")
            if w:
                report.warnings.append(w)

    prd_keys = {s.n for s in stories}
    for story in stories:
        current = existing.get(story.n)
        if current is None:
            _apply_create(run, repo, story, report, dry_run)
        elif current.get("sha") == story.src_sha:
            report.skipped.append(
                StoryOutcome(key=story.key, action="skip", number=current["number"],
                             title=story.issue_title, priority=story.priority,
                             reason="unchanged (src-sha matches)")
            )
        else:
            _apply_update(run, repo, story, current, report, dry_run)

    # Removed: existing story issues whose key is gone from the PRD — never touched, only flagged.
    for n in sorted(set(existing) - prd_keys):
        report.removed.append(
            StoryOutcome(key=f"us{n}", action="removed", number=existing[n]["number"],
                         reason="story no longer in the PRD; left intact for PO review")
        )
        report.warnings.append(
            f"story us{n} (issue #{existing[n]['number']}) is no longer in the PRD — left intact, "
            "flagged for the Product Owner (never auto-closed)."
        )

    return report


def _apply_create(
    run: Runner, repo: str, story: Story, report: BacklogReport, dry_run: bool
) -> None:
    if dry_run:
        report.created.append(
            StoryOutcome(key=story.key, action="create", title=story.issue_title,
                         priority=story.priority, reason="dry-run")
        )
        return
    cmd = ["gh", "issue", "create", "-R", repo, "--title", story.issue_title,
           "--body", _render_body(story), "--label", STORY_LABEL, "--label", DRAFT_LABEL]
    if story.priority:
        cmd += ["--label", story.priority]
    rc, out, err = run(cmd)
    if rc != 0:
        detail = err.strip() or out.strip()
        report.errors.append(f"`gh issue create` failed for {story.key}: {detail}")
        return
    match = _ISSUE_URL_RE.search(out)
    number = int(match.group(1)) if match else None
    report.created.append(
        StoryOutcome(key=story.key, action="create", number=number,
                     title=story.issue_title, priority=story.priority)
    )


def _apply_update(
    run: Runner, repo: str, story: Story, current: IssueDict, report: BacklogReport, dry_run: bool
) -> None:
    number = current["number"]
    if dry_run:
        report.updated.append(
            StoryOutcome(key=story.key, action="update", number=number,
                         title=story.issue_title, priority=story.priority, reason="dry-run")
        )
        return
    # Refresh the body (new src-sha) and re-derive the priority label; deliberately do NOT touch
    # status:draft — the PO owns publish state, and a content change must not silently un-publish.
    cmd = ["gh", "issue", "edit", str(number), "-R", repo, "--body", _render_body(story)]
    if story.priority:
        cmd += ["--add-label", story.priority]
    rc, out, err = run(cmd)
    if rc != 0:
        detail = err.strip() or out.strip()
        report.errors.append(f"`gh issue edit` failed for {story.key} (#{number}): {detail}")
        return
    report.updated.append(
        StoryOutcome(key=story.key, action="update", number=number,
                     title=story.issue_title, priority=story.priority)
    )


def reconcile_file(
    prd: Path,
    repo: str | None = None,
    runner: Runner | None = None,
    dry_run: bool = False,
    ensure_label: bool = True,
) -> BacklogReport:
    """Read the PRD from disk and reconcile. Missing file is a clear error."""
    if not prd.is_file():
        report = BacklogReport(repo=repo, dry_run=dry_run)
        report.errors.append(f"required input missing: {prd}")
        return report
    return reconcile_backlog(
        prd.read_text(encoding="utf-8"), repo=repo, runner=runner,
        dry_run=dry_run, ensure_label=ensure_label,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: reconcile the PRD backlog, print a JSON report, exit non-zero on any error."""
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile docs/PRD.md user stories into GitHub type:story issues (via gh): create "
            "new, update changed (by src-sha), skip unchanged, and flag removed stories for the PO."
        )
    )
    parser.add_argument("--prd", default="docs/PRD.md",
                        help="Path to the PRD (default: docs/PRD.md).")
    parser.add_argument("--repo", help="Target repository as org/repo (default: resolved via gh).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report the plan without creating or editing any issue.")
    parser.add_argument("--no-label", action="store_true",
                        help="Do not attempt to ensure backlog labels exist.")
    args = parser.parse_args(argv)

    report = reconcile_file(
        Path(args.prd), repo=args.repo, dry_run=args.dry_run, ensure_label=not args.no_label
    )
    print(json.dumps(report.to_dict(), indent=2))

    for w in report.warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not report.ok:
        print(f"ERROR: PRD backlog sync failed with {len(report.errors)} error(s):",
              file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
