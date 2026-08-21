"""Unit tests for preflight.py."""

from __future__ import annotations

import json

import pytest

from scripts.preflight import main, run_checks

# Canonical "everything is provisioned correctly" command responses.
GOOD = {
    ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
    ("git", "remote", "get-url", "origin"): (0, "https://github.com/acme/widgets.git\n", ""),
    ("gh", "auth", "status"): (0, "Logged in to github.com\n", ""),
    (
        "gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name",
    ): (0, "main\n", ""),
    (
        "gh", "api", "repos/{owner}/{repo}/branches/main", "--jq", ".protected",
    ): (0, "true\n", ""),
}


def _runner(overrides: dict | None = None):
    table = dict(GOOD)
    if overrides:
        table.update(overrides)

    def run(cmd):
        return table.get(tuple(cmd), (1, "", f"unexpected command: {list(cmd)}"))

    return run


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_all_prerequisites_met() -> None:
    report = run_checks(runner=_runner())
    assert report.is_valid
    assert {c.name for c in report.checks} == {
        "git-worktree",
        "origin-remote",
        "gh-auth",
        "default-branch",
        "main-protection",
    }
    assert report.failures == []


def test_not_a_git_worktree_fails() -> None:
    report = run_checks(
        runner=_runner({("git", "rev-parse", "--is-inside-work-tree"): (128, "", "fatal: not a git repo")})
    )
    assert not report.is_valid
    assert not _check(report, "git-worktree").ok


def test_missing_origin_fails() -> None:
    report = run_checks(
        runner=_runner({("git", "remote", "get-url", "origin"): (2, "", "error: No such remote")})
    )
    assert not _check(report, "origin-remote").ok


def test_ssh_origin_rejected() -> None:
    report = run_checks(
        runner=_runner({("git", "remote", "get-url", "origin"): (0, "git@github.com:acme/widgets.git\n", "")})
    )
    c = _check(report, "origin-remote")
    assert not c.ok
    assert "SSH" in c.detail


def test_ssh_scheme_origin_rejected() -> None:
    report = run_checks(
        runner=_runner({("git", "remote", "get-url", "origin"): (0, "ssh://git@github.com/acme/w.git\n", "")})
    )
    assert not _check(report, "origin-remote").ok


def test_gh_not_authenticated_fails() -> None:
    report = run_checks(
        runner=_runner({("gh", "auth", "status"): (1, "", "You are not logged into any GitHub hosts")})
    )
    assert not _check(report, "gh-auth").ok


def test_gh_not_installed_fails() -> None:
    report = run_checks(
        runner=_runner({("gh", "auth", "status"): (127, "", "command not found: 'gh'")})
    )
    assert not _check(report, "gh-auth").ok


def test_default_branch_not_main_fails() -> None:
    report = run_checks(
        runner=_runner(
            {
                (
                    "gh", "repo", "view", "--json", "defaultBranchRef", "--jq",
                    ".defaultBranchRef.name",
                ): (0, "master\n", "")
            }
        )
    )
    c = _check(report, "default-branch")
    assert not c.ok
    assert "master" in c.detail


def test_main_not_protected_fails() -> None:
    report = run_checks(
        runner=_runner(
            {("gh", "api", "repos/{owner}/{repo}/branches/main", "--jq", ".protected"): (0, "false\n", "")}
        )
    )
    c = _check(report, "main-protection")
    assert not c.ok
    assert "protection" in c.detail.lower()


def test_main_protection_unreadable_fails() -> None:
    report = run_checks(
        runner=_runner(
            {("gh", "api", "repos/{owner}/{repo}/branches/main", "--jq", ".protected"): (1, "", "HTTP 404")}
        )
    )
    assert not _check(report, "main-protection").ok


def test_main_cli_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("scripts.preflight._default_runner", _runner())
    code = main([])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["valid"] is True


def test_main_cli_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "scripts.preflight._default_runner",
        _runner({("gh", "auth", "status"): (1, "", "not logged in")}),
    )
    code = main([])
    assert code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False
    assert "gh-auth" in captured.err
