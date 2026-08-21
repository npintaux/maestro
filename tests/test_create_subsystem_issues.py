"""Unit tests for create_subsystem_issues.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.create_subsystem_issues import (
    _branch_slug,
    _render_body,
    main,
    reconcile_subsystem_issues,
)

REPO = "npintaux/maestro"

# US-1 -> link_store; US-2 -> link_store, analytics
MATRIX = """
| User Story | Subsystems |
|---|---|
| US-1 | link_store |
| US-2 | link_store, analytics |
"""

# Two existing story issues stamped with prd-sync markers, as prd-to-backlog would leave them.
STORY_ISSUES = [
    {"number": 11, "title": "[US1] shorten a URL",
     "body": "As a user...\n<!-- prd-sync: key=us1 src-sha=abc -->"},
    {"number": 12, "title": "[US2] view analytics",
     "body": "As a user...\n<!-- prd-sync: key=us2 src-sha=def -->"},
]


class FakeGh:
    """Records gh invocations and replies from a scripted issue list."""

    def __init__(self, issues=None, *, repo=REPO, list_rc=0, create_rc=0, edit_rc=0,
                 label_rc=0, next_number=100):
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

    def created_bodies(self):
        return [cmd[cmd.index("--body") + 1] for cmd in self.calls
                if cmd[:3] == ["gh", "issue", "create"]]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_branch_slug_snake_to_kebab() -> None:
    assert _branch_slug("redirect_resolver") == "redirect-resolver"
    assert _branch_slug("Link_Store") == "link-store"
    assert _branch_slug("analytics") == "analytics"


def test_render_body_has_marker_and_links() -> None:
    body = _render_body("link_store", ["US-1", "US-2"], {"US-1": 11, "US-2": 12})
    assert "<!-- maestro-subsystem: name=link_store -->" in body
    assert "- US-1 (#11)" in body
    assert "- US-2 (#12)" in body
    assert "issue/<this-issue-number>-link-store" in body


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_creates_one_issue_per_subsystem() -> None:
    gh = FakeGh(STORY_ISSUES)
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert report.ok, report.errors
    subsystems = sorted(o.subsystem for o in report.created)
    assert subsystems == ["analytics", "link_store"]
    assert all(o.number is not None for o in report.created)


def test_created_body_links_correct_story_issues() -> None:
    gh = FakeGh(STORY_ISSUES)
    reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    bodies = "\n".join(gh.created_bodies())
    # link_store serves US-1 (#11) and US-2 (#12); analytics serves only US-2 (#12).
    assert "- US-1 (#11)" in bodies
    assert "- US-2 (#12)" in bodies


def test_labels_issues_with_type_subsystem() -> None:
    gh = FakeGh(STORY_ISSUES)
    reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    create_calls = [c for c in gh.calls if c[:3] == ["gh", "issue", "create"]]
    assert create_calls
    for c in create_calls:
        assert "--label" in c and "type:subsystem" in c


def test_resolves_repo_when_not_given() -> None:
    gh = FakeGh(STORY_ISSUES)
    report = reconcile_subsystem_issues(MATRIX, runner=gh)
    assert report.repo == REPO
    assert any(c[:3] == ["gh", "repo", "view"] for c in gh.calls)


# --------------------------------------------------------------------------- #
# Idempotency / reconciliation
# --------------------------------------------------------------------------- #


def _existing_subsystem_issue(subsystem, number, stories, story_issues):
    from scripts.create_subsystem_issues import _render_body as render
    return {"number": number, "title": f"[subsystem] {subsystem}",
            "body": render(subsystem, stories, story_issues)}


def test_unchanged_issue_is_skipped_no_write() -> None:
    link = _existing_subsystem_issue("link_store", 20, ["US-1", "US-2"], {"US-1": 11, "US-2": 12})
    analytics = _existing_subsystem_issue("analytics", 21, ["US-2"], {"US-2": 12})
    gh = FakeGh(STORY_ISSUES + [link, analytics])
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert report.ok
    assert not report.created
    assert not report.updated
    assert sorted(o.subsystem for o in report.skipped) == ["analytics", "link_store"]
    assert not any(c[:3] == ["gh", "issue", "create"] for c in gh.calls)
    assert not any(c[:3] == ["gh", "issue", "edit"] for c in gh.calls)


def test_changed_body_triggers_update() -> None:
    stale = {"number": 20, "title": "[subsystem] link_store",
             "body": "<!-- maestro-subsystem: name=link_store -->\nstale body"}
    analytics = _existing_subsystem_issue("analytics", 21, ["US-2"], {"US-2": 12})
    gh = FakeGh(STORY_ISSUES + [stale, analytics])
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert report.ok
    assert [o.subsystem for o in report.updated] == ["link_store"]
    assert [o.subsystem for o in report.skipped] == ["analytics"]
    edit_calls = [c for c in gh.calls if c[:3] == ["gh", "issue", "edit"]]
    assert edit_calls and "20" in edit_calls[0]


def test_story_matched_by_title_fallback() -> None:
    # No prd-sync marker; identity recovered from the [USn] title key.
    story_issues = [
        {"number": 11, "title": "[US1] shorten a URL", "body": "no marker here"},
        {"number": 12, "title": "[US-2] view analytics", "body": "no marker here"},
    ]
    gh = FakeGh(story_issues)
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert report.ok, report.errors
    assert len(report.created) == 2


# --------------------------------------------------------------------------- #
# It bites
# --------------------------------------------------------------------------- #


def test_missing_story_issue_is_fatal_and_writes_nothing() -> None:
    # Only US-1 has an issue; US-2 does not, so analytics + link_store cannot be linked.
    gh = FakeGh([STORY_ISSUES[0]])
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert not report.ok
    assert any("US-2" in e and "no GitHub story issue" in e for e in report.errors)
    assert not any(c[:3] == ["gh", "issue", "create"] for c in gh.calls)


def test_empty_matrix_is_error() -> None:
    gh = FakeGh(STORY_ISSUES)
    report = reconcile_subsystem_issues("# nothing tabular\n", repo=REPO, runner=gh)
    assert not report.ok
    assert any("no subsystems" in e for e in report.errors)


def test_issue_list_failure_is_error() -> None:
    gh = FakeGh(STORY_ISSUES, list_rc=1)
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert not report.ok
    assert any("gh issue list" in e for e in report.errors)


def test_create_failure_is_surfaced() -> None:
    gh = FakeGh(STORY_ISSUES, create_rc=1)
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert not report.ok
    assert any("gh issue create" in e for e in report.errors)


def test_label_failure_is_warning_not_fatal() -> None:
    gh = FakeGh(STORY_ISSUES, label_rc=1)
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh)
    assert report.ok, report.errors
    assert report.warnings
    assert len(report.created) == 2


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_dry_run_plans_without_writing() -> None:
    gh = FakeGh(STORY_ISSUES)
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh, dry_run=True)
    assert report.ok
    assert len(report.created) == 2
    assert not any(c[:3] == ["gh", "issue", "create"] for c in gh.calls)
    assert not any(c[:3] == ["gh", "label", "create"] for c in gh.calls)


def test_dry_run_still_fails_on_missing_story() -> None:
    gh = FakeGh([STORY_ISSUES[0]])  # US-2 absent
    report = reconcile_subsystem_issues(MATRIX, repo=REPO, runner=gh, dry_run=True)
    assert not report.ok


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_main_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--traceability", str(tmp_path / "nope.md"), "--repo", REPO, "--dry-run"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_main_dry_run_pass(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    trace = tmp_path / "traceability.md"
    trace.write_text(MATRIX)
    gh = FakeGh(STORY_ISSUES)
    monkeypatch.setattr("scripts.create_subsystem_issues._default_runner", gh)
    code = main(["--traceability", str(trace), "--repo", REPO, "--dry-run"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
