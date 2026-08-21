"""Unit tests for worktree_manager.py — per-subsystem git worktree isolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.worktree_manager import (
    create_worktrees,
    list_worktrees,
    main,
    remove_worktree,
    teardown,
)

ROOT = "/repo"
INTEGRATION = "maestro/url-shortener"


def _wt_block(path: str, branch: str | None, head: str = "abc123") -> str:
    lines = [f"worktree {path}", f"HEAD {head}"]
    lines.append(f"branch refs/heads/{branch}" if branch else "detached")
    return "\n".join(lines)


class FakeGit:
    """Records git invocations; replies to worktree list / branch existence / add / remove."""

    def __init__(self, *, root=ROOT, worktrees=None, existing_branches=(), add_rc=0,
                 remove_rc=0):
        self.root = root
        # worktrees: list of (path, branch) already registered
        self.worktrees = list(worktrees or [])
        self.existing_branches = set(existing_branches)
        self.add_rc = add_rc
        self.remove_rc = remove_rc
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return (0, self.root + "\n", "")
        if cmd[:4] == ["git", "worktree", "list", "--porcelain"]:
            blocks = [_wt_block(self.root, "main")]
            blocks += [_wt_block(p, b) for p, b in self.worktrees]
            return (0, "\n\n".join(blocks) + "\n", "")
        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            ref = cmd[-1].replace("refs/heads/", "")
            return (0 if ref in self.existing_branches else 1, "", "")
        if cmd[:3] == ["git", "worktree", "add"]:
            return (self.add_rc, "", "" if self.add_rc == 0 else "add failed")
        if cmd[:3] == ["git", "worktree", "remove"]:
            return (self.remove_rc, "", "" if self.remove_rc == 0 else "worktree is dirty")
        raise AssertionError(f"unexpected call: {cmd}")

    def did(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


# --------------------------------------------------------------------------- #
# create — happy path
# --------------------------------------------------------------------------- #


def test_create_cuts_new_branch_from_integration() -> None:
    git = FakeGit()
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver", "issue": 12}],
                              runner=git)
    assert report.ok, report.errors
    assert len(report.created) == 1
    action = report.created[0]
    assert action.branch == "issue/12-redirect-resolver"
    assert action.path == ".maestro/worktrees/redirect_resolver"
    add = git.did("git", "worktree", "add")[0]
    assert "-b" in add and "issue/12-redirect-resolver" in add
    assert INTEGRATION in add  # cut from the integration branch
    assert f"{ROOT}/.maestro/worktrees/redirect_resolver" in add


def test_create_attaches_existing_branch_without_dash_b() -> None:
    git = FakeGit(existing_branches=["issue/12-redirect-resolver"])
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver", "issue": 12}],
                              runner=git)
    assert report.ok
    add = git.did("git", "worktree", "add")[0]
    assert "-b" not in add
    assert "issue/12-redirect-resolver" in add
    assert INTEGRATION not in add  # attach existing, don't re-cut


def test_create_batch() -> None:
    git = FakeGit()
    report = create_worktrees(
        INTEGRATION,
        [{"subsystem": "redirect_resolver", "issue": 12}, {"subsystem": "link_store", "issue": 7}],
        runner=git,
    )
    assert report.ok
    assert {a.branch for a in report.created} == {"issue/12-redirect-resolver", "issue/7-link-store"}


def test_create_is_idempotent_when_already_present() -> None:
    git = FakeGit(worktrees=[(f"{ROOT}/.maestro/worktrees/redirect_resolver",
                              "issue/12-redirect-resolver")])
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver", "issue": 12}],
                              runner=git)
    assert report.ok
    assert not report.created
    assert len(report.skipped) == 1
    assert not git.did("git", "worktree", "add")  # no write on resume


# --------------------------------------------------------------------------- #
# create — it bites
# --------------------------------------------------------------------------- #


def test_create_refuses_protected_base() -> None:
    git = FakeGit()
    report = create_worktrees("main", [{"subsystem": "redirect_resolver", "issue": 12}], runner=git)
    assert not report.ok
    assert any("integration branch" in e for e in report.errors)
    assert not git.did("git", "worktree", "add")


def test_create_refuses_non_integration_base() -> None:
    git = FakeGit()
    report = create_worktrees("feature/foo", [{"subsystem": "x", "issue": 1}], runner=git)
    assert not report.ok
    assert not git.did("git", "worktree", "add")


def test_create_refuses_path_occupied_by_other_branch() -> None:
    git = FakeGit(worktrees=[(f"{ROOT}/.maestro/worktrees/redirect_resolver",
                              "issue/99-something-else")])
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver", "issue": 12}],
                              runner=git)
    assert not report.ok
    assert any("clobber" in e for e in report.errors)
    assert not git.did("git", "worktree", "add")


def test_create_rejects_invalid_spec() -> None:
    git = FakeGit()
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver"}], runner=git)
    assert not report.ok
    assert any("invalid spec" in e for e in report.errors)


def test_create_empty_specs_is_error() -> None:
    git = FakeGit()
    report = create_worktrees(INTEGRATION, [], runner=git)
    assert not report.ok


def test_create_surfaces_git_add_failure() -> None:
    git = FakeGit(add_rc=1)
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver", "issue": 12}],
                              runner=git)
    assert not report.ok
    assert any("git worktree add" in e for e in report.errors)


def test_create_dry_run_plans_without_writing() -> None:
    git = FakeGit()
    report = create_worktrees(INTEGRATION, [{"subsystem": "redirect_resolver", "issue": 12}],
                              runner=git, dry_run=True)
    assert report.ok
    assert report.created and report.created[0].action == "plan"
    assert not git.did("git", "worktree", "add")


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_returns_only_maestro_worktrees() -> None:
    git = FakeGit(worktrees=[
        (f"{ROOT}/.maestro/worktrees/redirect_resolver", "issue/12-redirect-resolver"),
        (f"{ROOT}/.maestro/worktrees/link_store", "issue/7-link-store"),
    ])
    report = list_worktrees(runner=git)
    assert report.ok
    paths = {w["path"] for w in report.listed}
    assert paths == {
        f"{ROOT}/.maestro/worktrees/redirect_resolver",
        f"{ROOT}/.maestro/worktrees/link_store",
    }
    assert ROOT not in paths  # the main checkout is excluded


# --------------------------------------------------------------------------- #
# remove / teardown
# --------------------------------------------------------------------------- #


def test_remove_worktree() -> None:
    git = FakeGit(worktrees=[(f"{ROOT}/.maestro/worktrees/redirect_resolver",
                              "issue/12-redirect-resolver")])
    report = remove_worktree("redirect_resolver", runner=git)
    assert report.ok
    assert len(report.removed) == 1
    rm = git.did("git", "worktree", "remove")[0]
    assert f"{ROOT}/.maestro/worktrees/redirect_resolver" in rm


def test_remove_absent_is_idempotent() -> None:
    git = FakeGit()
    report = remove_worktree("redirect_resolver", runner=git)
    assert report.ok
    assert report.skipped and not report.removed
    assert not git.did("git", "worktree", "remove")


def test_remove_dirty_fails_without_force() -> None:
    git = FakeGit(worktrees=[(f"{ROOT}/.maestro/worktrees/redirect_resolver",
                              "issue/12-redirect-resolver")], remove_rc=1)
    report = remove_worktree("redirect_resolver", runner=git)
    assert not report.ok
    assert any("--force" in e for e in report.errors)


def test_remove_force_passes_flag() -> None:
    git = FakeGit(worktrees=[(f"{ROOT}/.maestro/worktrees/redirect_resolver",
                              "issue/12-redirect-resolver")])
    remove_worktree("redirect_resolver", runner=git, force=True)
    rm = git.did("git", "worktree", "remove")[0]
    assert "--force" in rm


def test_teardown_removes_all_maestro_worktrees() -> None:
    git = FakeGit(worktrees=[
        (f"{ROOT}/.maestro/worktrees/redirect_resolver", "issue/12-redirect-resolver"),
        (f"{ROOT}/.maestro/worktrees/link_store", "issue/7-link-store"),
    ])
    report = teardown(runner=git)
    assert report.ok
    assert {a.subsystem for a in report.removed} == {"redirect_resolver", "link_store"}
    assert len(git.did("git", "worktree", "remove")) == 2


def test_teardown_dry_run_writes_nothing() -> None:
    git = FakeGit(worktrees=[(f"{ROOT}/.maestro/worktrees/redirect_resolver",
                              "issue/12-redirect-resolver")])
    report = teardown(runner=git, dry_run=True)
    assert report.ok
    assert report.removed and report.removed[0].action == "plan"
    assert not git.did("git", "worktree", "remove")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_main_create_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([{"subsystem": "redirect_resolver", "issue": 12}]), encoding="utf-8")
    code = main(["--repo-root", str(tmp_path), "create", "--integration", INTEGRATION,
                 "--spec", str(spec), "--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["ok"] is True
    assert out["command"] == "create"


def test_main_create_bad_base_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["create", "--integration", "main", "--subsystem", "x", "--issue", "1",
                 "--dry-run"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_main_create_requires_spec_or_pair(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["create", "--integration", INTEGRATION])
    assert code == 1
    assert any("--spec" in e for e in json.loads(capsys.readouterr().out)["errors"])
