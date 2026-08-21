"""Unit tests for commit_artifacts.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.commit_artifacts import commit_artifacts, main


class FakeGit:
    """Records git calls and returns canned results. ``has_changes`` drives diff --cached."""

    def __init__(self, has_changes: bool = True, add_rc: int = 0, commit_rc: int = 0):
        self.has_changes = has_changes
        self.add_rc = add_rc
        self.commit_rc = commit_rc
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if "add" in cmd:
            return (self.add_rc, "", "" if self.add_rc == 0 else "add boom")
        if "diff" in cmd:
            return (1 if self.has_changes else 0, "", "")
        if "commit" in cmd:
            return (self.commit_rc, "[maestro/x abc] freeze", "" if self.commit_rc == 0 else "commit boom")
        if "rev-parse" in cmd and "HEAD" in cmd:
            return (0, "deadbeef\n", "")
        return (0, "", "")

    def commit_message(self) -> str | None:
        for cmd in self.calls:
            if "commit" in cmd:
                return cmd[cmd.index("-m") + 1]
        return None


def _on(branch: str):
    return lambda _root: branch


def _write_prd(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "PRD.md").write_text("# PRD\n")


def _write_architecture(root: Path) -> None:
    docs = root / "docs"
    (docs / "adr").mkdir(parents=True, exist_ok=True)
    (docs / "adr" / "0001-choose-run.md").write_text("# ADR 1\n")
    (docs / "architecture.md").write_text("# Arch\n")
    (docs / "security.md").write_text("# Sec\n")
    (docs / "traceability.md").write_text("# Trace\n")


def _write_spec(root: Path, subsystem: str) -> None:
    base = root / "src" / "modules" / subsystem
    base.mkdir(parents=True, exist_ok=True)
    (base / "SPEC.md").write_text("# SPEC\n")
    (base / "openapi.yaml").write_text("openapi: 3.0.0\n")


def _write_tests(root: Path, subsystem: str) -> None:
    contract = root / "tests" / "contract" / subsystem
    behavioral = root / "tests" / "behavioral" / subsystem
    contract.mkdir(parents=True, exist_ok=True)
    behavioral.mkdir(parents=True, exist_ok=True)
    (contract / f"test_contract_{subsystem}.py").write_text("def test_contract(): ...\n")
    (behavioral / f"test_behavioral_{subsystem}.py").write_text("def test_behavioral(): ...\n")
    lock = root / ".maestro" / "red_lock"
    lock.mkdir(parents=True, exist_ok=True)
    (lock / f"{subsystem}.json").write_text('{"locked": true}\n')


# --------------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------------- #


def test_prd_commit_success(tmp_path: Path) -> None:
    _write_prd(tmp_path)
    git = FakeGit()
    report = commit_artifacts(
        "prd", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/shortener")
    )
    assert report.ok and report.committed
    assert report.message == "docs(prd): freeze PRD [Gate 0]"
    assert report.paths == ["docs/PRD.md"]
    assert report.sha == "deadbeef"


def test_architecture_commit_success(tmp_path: Path) -> None:
    _write_architecture(tmp_path)
    git = FakeGit()
    report = commit_artifacts(
        "architecture", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x")
    )
    assert report.ok and report.committed
    assert "docs/adr" in report.paths and "docs/traceability.md" in report.paths


def test_spec_commit_success_with_issue(tmp_path: Path) -> None:
    _write_spec(tmp_path, "billing")
    git = FakeGit()
    report = commit_artifacts(
        "spec", subsystem="billing", issue=12, repo_root=tmp_path, runner=git,
        branch_resolver=_on("maestro/x"),
    )
    assert report.ok and report.committed
    assert report.message == "docs(spec): freeze billing contract [Gate 1] (#12)"
    assert git.commit_message() == "docs(spec): freeze billing contract [Gate 1] (#12)"


def test_ui_spec_commit_success_with_issue(tmp_path: Path) -> None:
    base = tmp_path / "src" / "modules" / "storefront"
    base.mkdir(parents=True, exist_ok=True)
    (base / "ui-spec.json").write_text('{"screens": []}\n')
    git = FakeGit()
    report = commit_artifacts(
        "ui-spec", subsystem="storefront", issue=21, repo_root=tmp_path, runner=git,
        branch_resolver=_on("maestro/x"),
    )
    assert report.ok and report.committed
    assert report.paths == ["src/modules/storefront/ui-spec.json"]
    assert report.message == "docs(ui-spec): freeze storefront UI contract [Gate UI] (#21)"


def test_ui_spec_without_subsystem_fails(tmp_path: Path) -> None:
    git = FakeGit()
    report = commit_artifacts(
        "ui-spec", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x")
    )
    assert not report.ok
    assert "ui-spec" in (report.reason or "") and "--subsystem" in (report.reason or "")


def test_tests_commit_success_freezes_locked_suite(tmp_path: Path) -> None:
    _write_tests(tmp_path, "redirect_resolver")
    git = FakeGit()
    report = commit_artifacts(
        "tests", subsystem="redirect_resolver", repo_root=tmp_path, runner=git,
        branch_resolver=_on("maestro/url-shortener"),
    )
    assert report.ok and report.committed
    assert report.message == (
        "test(redlock): freeze & lock redirect_resolver orthogonal suite [Phase 3]"
    )
    assert report.paths == [
        "tests/contract/redirect_resolver",
        "tests/behavioral/redirect_resolver",
        ".maestro/red_lock/redirect_resolver.json",
    ]


def test_tests_without_subsystem_fails(tmp_path: Path) -> None:
    git = FakeGit()
    report = commit_artifacts("tests", repo_root=tmp_path, runner=git,
                              branch_resolver=_on("maestro/x"))
    assert not report.ok
    assert "subsystem" in report.reason


def test_tests_missing_redlock_manifest_fails(tmp_path: Path) -> None:
    """Without a locked manifest, the suite cannot be frozen — worktrees would lack the oracle."""
    _write_tests(tmp_path, "redirect_resolver")
    (tmp_path / ".maestro" / "red_lock" / "redirect_resolver.json").unlink()
    git = FakeGit()
    report = commit_artifacts(
        "tests", subsystem="redirect_resolver", repo_root=tmp_path, runner=git,
        branch_resolver=_on("maestro/x"),
    )
    assert not report.ok
    assert any("red_lock" in m for m in report.missing)


def test_tests_empty_contract_dir_fails(tmp_path: Path) -> None:
    _write_tests(tmp_path, "redirect_resolver")
    (tmp_path / "tests" / "contract" / "redirect_resolver"
     / "test_contract_redirect_resolver.py").unlink()
    git = FakeGit()
    report = commit_artifacts(
        "tests", subsystem="redirect_resolver", repo_root=tmp_path, runner=git,
        branch_resolver=_on("maestro/x"),
    )
    assert not report.ok
    assert any("tests/contract/redirect_resolver" in m for m in report.missing)


def test_commit_scoped_to_artifact_paths_only(tmp_path: Path) -> None:
    """Forced shape: the commit pathspec is exactly the group's artifacts."""
    _write_prd(tmp_path)
    git = FakeGit()
    commit_artifacts("prd", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x"))
    commit_cmd = next(c for c in git.calls if "commit" in c)
    assert commit_cmd[-1] == "docs/PRD.md"
    assert commit_cmd[commit_cmd.index("--") + 1 :] == ["docs/PRD.md"]


# --------------------------------------------------------------------------- #
# Non-negotiables
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("branch", ["main", "master"])
def test_refuses_protected_branch(tmp_path: Path, branch: str) -> None:
    _write_prd(tmp_path)
    git = FakeGit()
    report = commit_artifacts("prd", repo_root=tmp_path, runner=git, branch_resolver=_on(branch))
    assert not report.ok and not report.committed
    assert branch in report.reason
    assert not any("commit" in c for c in git.calls)  # never even attempted to commit


def test_missing_prd_fails(tmp_path: Path) -> None:
    git = FakeGit()
    report = commit_artifacts("prd", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x"))
    assert not report.ok
    assert report.missing == ["docs/PRD.md"]


def test_architecture_missing_adr_dir_fails(tmp_path: Path) -> None:
    # everything except the ADR directory
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("x")
    (docs / "security.md").write_text("x")
    (docs / "traceability.md").write_text("x")
    git = FakeGit()
    report = commit_artifacts(
        "architecture", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x")
    )
    assert not report.ok
    assert any("docs/adr" in m for m in report.missing)


def test_architecture_empty_adr_dir_fails(tmp_path: Path) -> None:
    _write_architecture(tmp_path)
    # remove the only ADR, leaving an empty dir
    (tmp_path / "docs" / "adr" / "0001-choose-run.md").unlink()
    git = FakeGit()
    report = commit_artifacts(
        "architecture", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x")
    )
    assert not report.ok
    assert any("docs/adr" in m for m in report.missing)


def test_spec_without_subsystem_fails(tmp_path: Path) -> None:
    git = FakeGit()
    report = commit_artifacts("spec", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x"))
    assert not report.ok
    assert "subsystem" in report.reason


def test_nothing_to_commit_is_idempotent_success(tmp_path: Path) -> None:
    _write_prd(tmp_path)
    git = FakeGit(has_changes=False)
    report = commit_artifacts("prd", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x"))
    assert report.ok and not report.committed
    assert "already frozen" in report.note
    assert not any("commit" in c for c in git.calls)


def test_git_commit_failure_reported(tmp_path: Path) -> None:
    _write_prd(tmp_path)
    git = FakeGit(commit_rc=1)
    report = commit_artifacts("prd", repo_root=tmp_path, runner=git, branch_resolver=_on("maestro/x"))
    assert not report.ok
    assert "git commit failed" in report.reason


def test_dry_run_commits_nothing(tmp_path: Path) -> None:
    _write_prd(tmp_path)
    git = FakeGit()
    report = commit_artifacts(
        "prd", repo_root=tmp_path, runner=git, dry_run=True, branch_resolver=_on("maestro/x")
    )
    assert report.ok and not report.committed
    assert git.calls == []  # nothing executed at all
    assert "dry-run" in report.note


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_main_cli_missing_artifact_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # On a real (empty) repo path with no PRD, this fails on missing artifact.
    monkeypatch.setattr("scripts.commit_artifacts._resolve_current_branch", lambda run, root: "maestro/x")
    code = main(["prd", "--repo-root", str(tmp_path)])
    assert code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False


# --------------------------------------------------------------------------- #
# End-to-end against a real git repository
# --------------------------------------------------------------------------- #


def test_end_to_end_real_git_repo(tmp_path: Path) -> None:
    """Prove the real subprocess path: init a repo, freeze the PRD on an integration branch."""
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    git("checkout", "-q", "-b", "maestro/e2e")
    _write_prd(tmp_path)

    report = commit_artifacts("prd", repo_root=tmp_path)
    assert report.ok and report.committed, report.reason
    assert report.branch == "maestro/e2e"
    assert report.sha

    # The commit exists, carries the forced message, and contains ONLY docs/PRD.md.
    log = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", "--pretty=%s"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert log == "docs(prd): freeze PRD [Gate 0]"
    files = subprocess.run(
        ["git", "-C", str(tmp_path), "show", "--name-only", "--pretty=format:"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert files == ["docs/PRD.md"]

    # Re-running with no changes is an idempotent no-op.
    again = commit_artifacts("prd", repo_root=tmp_path)
    assert again.ok and not again.committed
