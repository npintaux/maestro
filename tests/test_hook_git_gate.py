"""Unit tests for hook_git_gate.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.hook_git_gate import (
    evaluate_command,
    main,
    process_pre_tool_use_hook,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_command_payload(command: str, cwd: str | None = None) -> str:
    args: dict[str, str] = {"CommandLine": command}
    if cwd is not None:
        args["Cwd"] = cwd
    return json.dumps({"toolCall": {"name": "run_command", "args": args}})


def _on(branch: str | None):
    """Branch resolver stub: pretend the repo's current branch is ``branch``."""
    return lambda _cwd: branch


# --------------------------------------------------------------------------- #
# Fail-open: anything the gate cannot confidently evaluate is allowed.
# --------------------------------------------------------------------------- #


def test_empty_stdin_allows() -> None:
    assert process_pre_tool_use_hook("", branch_resolver=_on("main"))["decision"] == "allow"


def test_invalid_json_allows() -> None:
    assert process_pre_tool_use_hook("{nope", branch_resolver=_on("main"))["decision"] == "allow"


def test_non_dict_json_allows() -> None:
    assert process_pre_tool_use_hook("[1,2]", branch_resolver=_on("main"))["decision"] == "allow"


def test_non_run_command_tool_allows() -> None:
    payload = json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": "x"}}})
    assert process_pre_tool_use_hook(payload, branch_resolver=_on("main"))["decision"] == "allow"


def test_missing_command_line_allows() -> None:
    payload = json.dumps({"toolCall": {"name": "run_command", "args": {}}})
    assert process_pre_tool_use_hook(payload, branch_resolver=_on("main"))["decision"] == "allow"


def test_non_git_command_allows() -> None:
    assert evaluate_command("ls -la && echo hi", "main")["decision"] == "allow"


def test_git_non_gated_subcommand_allows() -> None:
    # `git log --grep=commit` must not be mistaken for a commit.
    assert evaluate_command("git log --grep=commit", "main")["decision"] == "allow"
    assert evaluate_command("git status", "main")["decision"] == "allow"


def test_commit_with_undeterminable_branch_allows() -> None:
    # Branch resolver returns None (e.g. not a git repo) -> fail open.
    assert evaluate_command("git commit -m 'x'", None)["decision"] == "allow"


# --------------------------------------------------------------------------- #
# Rule 1: no commit to a protected branch.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("branch", ["main", "master"])
def test_commit_on_protected_branch_denied(branch: str) -> None:
    res = evaluate_command("git commit -m 'wip'", branch)
    assert res["decision"] == "deny"
    assert _reason(res).startswith("PreToolUse Git Gate")
    assert branch in _reason(res)


def test_commit_on_integration_branch_allowed() -> None:
    assert evaluate_command("git commit -m 'freeze PRD'", "maestro/url-shortener")["decision"] == "allow"


def test_commit_on_subsystem_branch_allowed() -> None:
    assert evaluate_command("git commit -am 'feat'", "issue/12-redirect-resolver")["decision"] == "allow"


def test_commit_detected_across_chain() -> None:
    res = evaluate_command("git add -A && git commit -m 'x'", "main")
    assert res["decision"] == "deny"


def test_commit_with_dash_c_global_flag_denied() -> None:
    # `git -C . commit` and `git -c user.name=x commit` must still be seen as commits.
    assert evaluate_command("git -C . commit -m 'x'", "main")["decision"] == "deny"
    assert evaluate_command("git -c user.name=bot commit -m 'x'", "main")["decision"] == "deny"


# --------------------------------------------------------------------------- #
# Rule 2: no push to a protected branch.
# --------------------------------------------------------------------------- #


def test_push_explicit_main_denied() -> None:
    assert evaluate_command("git push origin main", "issue/1-foo")["decision"] == "deny"


def test_push_refspec_to_master_denied() -> None:
    assert evaluate_command("git push origin HEAD:master", "issue/1-foo")["decision"] == "deny"


def test_push_force_to_main_denied() -> None:
    assert evaluate_command("git push -f origin main", "issue/1-foo")["decision"] == "deny"
    assert evaluate_command("git push origin +refs/heads/main", "issue/1-foo")["decision"] == "deny"


def test_bare_push_from_protected_branch_denied() -> None:
    assert evaluate_command("git push", "main")["decision"] == "deny"


def test_bare_push_from_subsystem_branch_allowed() -> None:
    assert evaluate_command("git push -u origin HEAD", "issue/12-foo")["decision"] == "allow"


def test_push_subsystem_branch_allowed() -> None:
    assert evaluate_command("git push origin issue/12-foo", "issue/12-foo")["decision"] == "allow"


def test_push_value_flag_not_confused_for_target() -> None:
    # `--repo main` would be pathological, but the value-flag skip must not crash.
    assert evaluate_command("git push -o ci.skip origin issue/9-x", "issue/9-x")["decision"] == "allow"


# --------------------------------------------------------------------------- #
# Rule 3: only Maestro-shaped branches may be created.
# --------------------------------------------------------------------------- #


def test_checkout_b_valid_subsystem_branch_allowed() -> None:
    assert evaluate_command("git checkout -b issue/12-redirect-resolver", "maestro/x")["decision"] == "allow"


def test_switch_c_valid_integration_branch_allowed() -> None:
    assert evaluate_command("git switch -c maestro/url-shortener", "main")["decision"] == "allow"


def test_checkout_b_arbitrary_branch_denied() -> None:
    res = evaluate_command("git checkout -b feature/random", "main")
    assert res["decision"] == "deny"
    assert "issue/<n>-<subsystem>" in _reason(res)


def test_checkout_b_main_denied() -> None:
    assert evaluate_command("git checkout -b main", "maestro/x")["decision"] == "deny"


def test_git_branch_create_arbitrary_denied() -> None:
    assert evaluate_command("git branch scratch", "maestro/x")["decision"] == "deny"


def test_git_branch_create_valid_allowed() -> None:
    assert evaluate_command("git branch issue/3-billing", "maestro/x")["decision"] == "allow"


def test_git_branch_list_allowed() -> None:
    assert evaluate_command("git branch", "main")["decision"] == "allow"
    assert evaluate_command("git branch -a", "main")["decision"] == "allow"


def test_git_branch_delete_allowed() -> None:
    # Deleting an arbitrary branch is not a creation -> not our concern.
    assert evaluate_command("git branch -D feature/random", "maestro/x")["decision"] == "allow"


def test_plain_checkout_existing_branch_allowed() -> None:
    # Switching to an existing branch (no -b/-c) is not a creation.
    assert evaluate_command("git checkout main", "issue/1-foo")["decision"] == "allow"


def test_subsystem_branch_shape_rejects_uppercase_and_underscore() -> None:
    assert evaluate_command("git checkout -b issue/12-Redirect", "main")["decision"] == "deny"
    assert evaluate_command("git checkout -b issue/foo-bar", "main")["decision"] == "deny"


# --------------------------------------------------------------------------- #
# CLI + wiring.
# --------------------------------------------------------------------------- #


def test_main_cli_deny(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin.read", lambda: _run_command_payload("git commit -m x"))
    code = main(["--branch", "main"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["decision"] == "deny"
    assert data["reason"].startswith("PreToolUse Git Gate")


def test_main_cli_allow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin.read", lambda: _run_command_payload("git commit -m x"))
    code = main(["--branch", "issue/7-cart"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["decision"] == "allow"


def test_runs_as_direct_script_and_denies(tmp_path: Path) -> None:
    """Antigravity runs the gate as `python3 scripts/hook_git_gate.py`.

    Drive the real invocation (repo root NOT on PYTHONPATH) end-to-end. The tmp_path cwd
    is not a git repo, so branch resolution fails open for the commit rule; a push to an
    explicit `main` refspec does not depend on branch resolution, so it must still deny.
    """
    script = REPO_ROOT / "scripts" / "hook_git_gate.py"
    payload = _run_command_payload("git push origin main", cwd=str(tmp_path))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["decision"] == "deny"


def test_hooks_json_wires_git_gate() -> None:
    """hooks.json must gate `run_command` and wire the git gate script."""
    cfg = json.loads((REPO_ROOT / "hooks.json").read_text())
    entry = cfg["git-gate"]["PreToolUse"][0]
    assert entry["matcher"] == "run_command"
    assert "hook_git_gate.py" in entry["hooks"][0]["command"]
    # The pre-existing boundary guard must remain wired.
    assert "boundary-guard" in cfg


def _reason(res: dict[str, str]) -> str:
    return res.get("reason", "")
