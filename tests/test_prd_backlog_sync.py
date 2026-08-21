"""Unit tests for prd_backlog_sync.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prd_backlog_sync import (
    _derive_priority,
    _parse_prd_stories,
    _render_body,
    _src_sha,
    main,
    reconcile_backlog,
)

REPO = "npintaux/maestro"

PRD = """# Product Requirements

## 5. Agile User Stories & Acceptance Criteria
### Epic 1: Links
#### Story US-1: Shorten a URL
* **As a** user,
* **I want to** shorten a long URL,
* **So that** I can share it. This is a must-have.
* **Acceptance Criteria**:
  - [ ] **AC-1.1**: Given a URL, when I submit, then I get a short code.

#### Story US-2: View analytics
* **As a** user,
* **I want to** view click analytics,
* **So that** I understand usage. Nice to have.
* **Acceptance Criteria**:
  - [ ] **AC-2.1**: Given a short code, when I view, then I see click counts.

---

## 6. Constraints
Out of scope: billing.
"""


class FakeGh:
    """Records gh invocations and replies from a scripted issue list."""

    def __init__(self, issues=None, *, repo=REPO, list_rc=0, create_rc=0, edit_rc=0,
                 label_rc=0, next_number=200):
        self.issues = list(issues or [])
        self.repo = repo
        self.list_rc = list_rc
        self.create_rc = create_rc
        self.edit_rc = edit_rc
        self.label_rc = label_rc
        self.next_number = next_number
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "repo", "view"]:
            return (0, self.repo + "\n", "")
        if cmd[:3] == ["gh", "issue", "list"]:
            if self.list_rc != 0:
                return (self.list_rc, "", "boom")
            return (0, json.dumps(self.issues), "")
        if cmd[:3] == ["gh", "label", "create"]:
            return (self.label_rc, "", "" if self.label_rc == 0 else "no perms")
        if cmd[:3] == ["gh", "issue", "create"]:
            if self.create_rc != 0:
                return (self.create_rc, "", "create failed")
            num = self.next_number
            self.next_number += 1
            return (0, f"https://github.com/{self.repo}/issues/{num}\n", "")
        if cmd[:3] == ["gh", "issue", "edit"]:
            return (self.edit_rc, "", "" if self.edit_rc == 0 else "edit failed")
        raise AssertionError(f"unexpected gh call: {cmd}")

    def creates(self):
        return [c for c in self.calls if c[:3] == ["gh", "issue", "create"]]

    def edits(self):
        return [c for c in self.calls if c[:3] == ["gh", "issue", "edit"]]

    def _arg(self, cmd, flag):
        return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _issue_for(story_n, sha, number, *, title=None):
    """Build an existing gh issue for story n stamped with a prd-sync marker."""
    return {
        "number": number,
        "title": title or f"[US{story_n}] whatever",
        "body": f"<!-- prd-sync: key=us{story_n} src-sha={sha} -->\n# body",
    }


# --------------------------------------------------------------------------- #
# Parsing + helpers
# --------------------------------------------------------------------------- #


def test_parses_two_stories() -> None:
    stories, warnings = _parse_prd_stories(PRD)
    assert [s.n for s in stories] == [1, 2]
    assert stories[0].title == "Shorten a URL"
    assert stories[1].title == "View analytics"
    assert not warnings


def test_section_stops_at_boundary() -> None:
    stories, _ = _parse_prd_stories(PRD)
    # US-1's section must not bleed into US-2 or the Section 6 boundary.
    assert "AC-1.1" in stories[0].section
    assert "AC-2.1" not in stories[0].section
    assert "billing" not in stories[1].section


def test_tolerant_key_forms() -> None:
    prd = "#### Story US-1: A\ntext\n# [US2] B\ntext\n## US-3 — C\ntext\n"
    stories, _ = _parse_prd_stories(prd)
    assert [s.n for s in stories] == [1, 2, 3]


def test_duplicate_heading_warns_keeps_first() -> None:
    prd = "#### Story US-1: First\nx\n#### Story US-1: Dup\ny\n"
    stories, warnings = _parse_prd_stories(prd)
    assert [s.n for s in stories] == [1]
    assert stories[0].title == "First"
    assert any("duplicate story heading US-1" in w for w in warnings)


def test_derive_priority() -> None:
    assert _derive_priority("this is a must-have feature") == "must-have"
    assert _derive_priority("nice to have someday") == "could-have"
    assert _derive_priority("no signal here") is None


def test_src_sha_stable_and_sensitive() -> None:
    a = _src_sha("hello\nworld")
    assert a == _src_sha("hello\nworld  ")  # trailing whitespace normalized
    assert a != _src_sha("hello\nWORLD")


def test_render_body_has_marker_and_source() -> None:
    stories, _ = _parse_prd_stories(PRD)
    body = _render_body(stories[0])
    assert f"src-sha={stories[0].src_sha}" in body
    assert "key=us1" in body
    assert "# [US1] Shorten a URL" in body
    assert "docs/PRD.md" in body


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


def test_all_new_creates_each() -> None:
    gh = FakeGh([])
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert report.ok, report.errors
    assert sorted(o.key for o in report.created) == ["us1", "us2"]
    assert len(gh.creates()) == 2


def test_new_issue_gets_story_and_draft_labels() -> None:
    gh = FakeGh([])
    reconcile_backlog(PRD, repo=REPO, runner=gh)
    for c in gh.creates():
        assert "type:story" in c
        assert "status:draft" in c
    # US-1 is must-have, US-2 is could-have (nice to have) -> priority labels applied.
    all_labels = " ".join(" ".join(c) for c in gh.creates())
    assert "must-have" in all_labels
    assert "could-have" in all_labels


def test_unchanged_story_skipped_no_write() -> None:
    stories, _ = _parse_prd_stories(PRD)
    existing = [_issue_for(s.n, s.src_sha, 300 + s.n) for s in stories]
    gh = FakeGh(existing)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert report.ok
    assert not report.created and not report.updated
    assert sorted(o.key for o in report.skipped) == ["us1", "us2"]
    assert not gh.creates() and not gh.edits()


def test_changed_story_updated() -> None:
    stories, _ = _parse_prd_stories(PRD)
    existing = [
        _issue_for(1, "deadbeef0000", 301),  # stale sha -> changed
        _issue_for(2, stories[1].src_sha, 302),  # matches -> unchanged
    ]
    gh = FakeGh(existing)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert report.ok
    assert [o.key for o in report.updated] == ["us1"]
    assert [o.key for o in report.skipped] == ["us2"]
    assert gh.edits() and "301" in gh.edits()[0]


def test_update_does_not_touch_draft_label() -> None:
    gh = FakeGh([_issue_for(1, "stale00", 301), _issue_for(2, "stale00", 302)])
    reconcile_backlog(PRD, repo=REPO, runner=gh)
    for c in gh.edits():
        assert "status:draft" not in c  # publish state is the PO's, never re-imposed on update


def test_title_fallback_forces_update() -> None:
    # Issue exists by [USn] title but has no marker -> sha unknown -> update to stamp it.
    existing = [{"number": 305, "title": "[US1] Shorten a URL", "body": "no marker"},
                {"number": 306, "title": "[US2] View analytics", "body": "no marker"}]
    gh = FakeGh(existing)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert report.ok
    assert sorted(o.key for o in report.updated) == ["us1", "us2"]
    assert not report.created


def test_removed_story_flagged_not_closed() -> None:
    stories, _ = _parse_prd_stories(PRD)
    existing = [_issue_for(s.n, s.src_sha, 300 + s.n) for s in stories]
    existing.append(_issue_for(9, "whatever", 309))  # us9 no longer in PRD
    gh = FakeGh(existing)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert report.ok
    assert [o.key for o in report.removed] == ["us9"]
    assert any("us9" in w for w in report.warnings)
    # Never closed/deleted: no gh call targets #309 for edit/close.
    assert not any("309" in " ".join(c) for c in gh.creates() + gh.edits())


def test_resolves_repo_when_not_given() -> None:
    gh = FakeGh([])
    report = reconcile_backlog(PRD, runner=gh)
    assert report.repo == REPO
    assert any(c[:3] == ["gh", "repo", "view"] for c in gh.calls)


# --------------------------------------------------------------------------- #
# It bites
# --------------------------------------------------------------------------- #


def test_no_stories_is_error() -> None:
    gh = FakeGh([])
    report = reconcile_backlog("# PRD with no stories\n", repo=REPO, runner=gh)
    assert not report.ok
    assert any("no User Stories" in e for e in report.errors)


def test_list_failure_is_error() -> None:
    gh = FakeGh([], list_rc=1)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert not report.ok
    assert any("gh issue list" in e for e in report.errors)


def test_create_failure_surfaced() -> None:
    gh = FakeGh([], create_rc=1)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert not report.ok
    assert any("gh issue create" in e for e in report.errors)


def test_label_failure_is_warning_not_fatal() -> None:
    gh = FakeGh([], label_rc=1)
    report = reconcile_backlog(PRD, repo=REPO, runner=gh)
    assert report.ok, report.errors
    assert report.warnings
    assert len(report.created) == 2


# --------------------------------------------------------------------------- #
# Dry run + CLI
# --------------------------------------------------------------------------- #


def test_dry_run_writes_nothing() -> None:
    gh = FakeGh([])
    report = reconcile_backlog(PRD, repo=REPO, runner=gh, dry_run=True)
    assert report.ok
    assert len(report.created) == 2
    assert not gh.creates()
    assert not any(c[:3] == ["gh", "label", "create"] for c in gh.calls)


def test_main_missing_prd(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--prd", str(tmp_path / "nope.md"), "--repo", REPO, "--dry-run"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_main_dry_run_pass(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    prd = tmp_path / "PRD.md"
    prd.write_text(PRD)
    gh = FakeGh([])
    monkeypatch.setattr("scripts.prd_backlog_sync._default_runner", gh)
    code = main(["--prd", str(prd), "--repo", REPO, "--dry-run"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert len(out["created"]) == 2
