"""Unit tests for ship_pr.py — the mechanical merge policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ship_pr import main, ship_integration, ship_subsystem

REPO = "npintaux/maestro"
INTEGRATION = "maestro/url-shortener"
SUBSYS_BRANCH = "issue/12-redirect-resolver"


class FakeGh:
    """Records gh/git invocations; scripts PR-list and merge replies."""

    def __init__(self, *, repo=REPO, existing_pr=None, create_rc=0, merge_rc=0, branch=None,
                 pr_number=42):
        self.repo = repo
        self.existing_pr = existing_pr  # (url, number) or None
        self.create_rc = create_rc
        self.merge_rc = merge_rc
        self.branch = branch
        self.pr_number = pr_number
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "repo", "view"]:
            return (0, self.repo + "\n", "")
        if cmd[:3] == ["git", "branch", "--show-current"]:
            return (0, (self.branch or "") + "\n", "")
        if cmd[:3] == ["gh", "pr", "list"]:
            if self.existing_pr:
                url, num = self.existing_pr
                return (0, json.dumps([{"url": url, "number": num}]), "")
            return (0, "[]", "")
        if cmd[:3] == ["gh", "pr", "create"]:
            if self.create_rc != 0:
                return (self.create_rc, "", "create failed")
            return (0, f"https://github.com/{self.repo}/pull/{self.pr_number}\n", "")
        if cmd[:3] == ["gh", "pr", "merge"]:
            return (self.merge_rc, "", "" if self.merge_rc == 0 else "merge failed")
        raise AssertionError(f"unexpected call: {cmd}")

    def did(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


def green(stage, subsystem):
    return (0, f"{stage} ok for {subsystem}")


def red_on(*failing):
    def runner(stage, subsystem):
        return (1 if stage in failing else 0, f"{stage} for {subsystem}")
    return runner


# --------------------------------------------------------------------------- #
# Subsystem ship — happy path
# --------------------------------------------------------------------------- #


def test_green_proof_machine_merges() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green)
    assert report.ok, report.errors
    assert report.merged is True
    assert [g.stage for g in report.proof] == ["gate-3", "gate-4", "redlock"]
    assert all(g.passed for g in report.proof)
    merge = gh.did("gh", "pr", "merge")
    assert merge and "--squash" in merge[0] and "--delete-branch" in merge[0]


def test_pr_body_closes_issue_derived_from_branch() -> None:
    gh = FakeGh()
    ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO, runner=gh, gate_runner=green)
    create = gh.did("gh", "pr", "create")[0]
    body = create[create.index("--body") + 1]
    assert "Closes #12" in body
    base = create[create.index("--base") + 1]
    head = create[create.index("--head") + 1]
    assert base == INTEGRATION and head == SUBSYS_BRANCH


def test_derives_subsystem_and_issue() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch="issue/7-link-store", repo=REPO,
                            runner=gh, gate_runner=green)
    assert report.ok
    title = gh.did("gh", "pr", "create")[0]
    joined = " ".join(title)
    assert "link-store" in joined and "#7" in joined


def test_frontend_subsystem_appends_gate_frontend_to_proof() -> None:
    """A UI subsystem (probe True) re-runs gate-frontend as part of the ship proof."""
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green, frontend_probe=lambda _s: True)
    assert report.ok, report.errors
    assert report.merged is True
    assert [g.stage for g in report.proof] == ["gate-3", "gate-4", "redlock", "gate-frontend"]
    assert all(g.passed for g in report.proof)


def test_frontend_gate_red_refuses_merge() -> None:
    """gate-frontend RED on a UI subsystem blocks the merge like any other proof stage."""
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=red_on("gate-frontend"),
                            frontend_probe=lambda _s: True)
    assert not report.ok
    assert report.merged is False
    assert gh.did("gh", "pr", "create")  # PR still opened
    assert not gh.did("gh", "pr", "merge")  # but never merged
    assert any(g.stage == "gate-frontend" and not g.passed for g in report.proof)


def test_backend_subsystem_skips_gate_frontend() -> None:
    """A backend-only subsystem (probe False) never runs gate-frontend."""
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green, frontend_probe=lambda _s: False)
    assert report.ok, report.errors
    assert [g.stage for g in report.proof] == ["gate-3", "gate-4", "redlock"]


# --------------------------------------------------------------------------- #
# Subsystem ship — it bites
# --------------------------------------------------------------------------- #


def test_red_proof_opens_pr_but_refuses_merge() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=red_on("gate-4"))
    assert not report.ok
    assert report.merged is False
    assert gh.did("gh", "pr", "create")  # PR still opened
    assert not gh.did("gh", "pr", "merge")  # but never merged
    assert any("RED" in e for e in report.errors)


def test_refuses_base_main() -> None:
    gh = FakeGh()
    report = ship_subsystem("main", current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green)
    assert not report.ok
    assert any("integration branch" in e for e in report.errors)
    assert not gh.did("gh", "pr", "create")


def test_refuses_non_integration_base() -> None:
    gh = FakeGh()
    report = ship_subsystem("feature/foo", current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green)
    assert not report.ok
    assert not gh.did("gh", "pr", "merge")


def test_refuses_when_not_on_subsystem_branch() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=INTEGRATION, repo=REPO,
                            runner=gh, gate_runner=green)
    assert not report.ok
    assert any("subsystem branch" in e for e in report.errors)


def test_no_merge_flag_opens_but_holds() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green, no_merge=True)
    assert report.ok
    assert report.merged is False
    assert gh.did("gh", "pr", "create")
    assert not gh.did("gh", "pr", "merge")


def test_merge_failure_surfaced() -> None:
    gh = FakeGh(merge_rc=1)
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green)
    assert not report.ok
    assert any("gh pr merge" in e for e in report.errors)


def test_existing_pr_is_reused() -> None:
    gh = FakeGh(existing_pr=(f"https://github.com/{REPO}/pull/99", 99))
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green)
    assert report.ok
    assert report.pr_number == 99
    assert not gh.did("gh", "pr", "create")  # reused, not recreated
    assert gh.did("gh", "pr", "merge")  # still merged on green


def test_dry_run_no_writes_reports_proof() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=green, dry_run=True)
    assert report.ok
    assert report.proof and all(g.passed for g in report.proof)
    assert not gh.did("gh", "pr", "create")
    assert not gh.did("gh", "pr", "merge")


def test_dry_run_red_proof_flags_error() -> None:
    gh = FakeGh()
    report = ship_subsystem(INTEGRATION, current_branch=SUBSYS_BRANCH, repo=REPO,
                            runner=gh, gate_runner=red_on("gate-3"), dry_run=True)
    assert not report.ok
    assert not gh.did("gh", "pr", "create")


# --------------------------------------------------------------------------- #
# Integration ship — opens, never merges
# --------------------------------------------------------------------------- #


def test_integration_opens_pr_never_merges() -> None:
    gh = FakeGh()
    report = ship_integration(INTEGRATION, base="main", repo=REPO, runner=gh)
    assert report.ok
    assert report.merged is False
    assert gh.did("gh", "pr", "create")
    assert not gh.did("gh", "pr", "merge")  # the whole point: human owns this merge
    create = gh.did("gh", "pr", "create")[0]
    assert create[create.index("--base") + 1] == "main"
    assert create[create.index("--head") + 1] == INTEGRATION


def test_integration_refuses_non_main_base() -> None:
    gh = FakeGh()
    report = ship_integration(INTEGRATION, base="develop", repo=REPO, runner=gh)
    assert not report.ok
    assert not gh.did("gh", "pr", "create")


def test_integration_refuses_bad_head() -> None:
    gh = FakeGh()
    report = ship_integration("issue/1-foo", base="main", repo=REPO, runner=gh)
    assert not report.ok


def test_integration_dry_run() -> None:
    gh = FakeGh()
    report = ship_integration(INTEGRATION, base="main", repo=REPO, runner=gh, dry_run=True)
    assert report.ok
    assert not gh.did("gh", "pr", "create")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_main_integration_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["integration", "--integration", INTEGRATION, "--repo", REPO, "--dry-run"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "integration"


def test_main_subsystem_bad_base_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["subsystem", "--integration", "main", "--repo", REPO, "--dry-run"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
