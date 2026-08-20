"""Unit tests for hook_boundary_guard.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.hook_boundary_guard import main, process_pre_tool_use_hook

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_hook_boundary_guard_no_subsystem() -> None:
    # No subsystem constraint active -> allow unconditionally
    payload = json.dumps(
        {"toolCall": {"name": "write_to_file", "args": {"TargetFile": "anything.py"}}}
    )
    res = process_pre_tool_use_hook(payload, subsystem_override="")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_empty_stdin() -> None:
    res = process_pre_tool_use_hook("", subsystem_override="billing")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_invalid_json() -> None:
    res = process_pre_tool_use_hook("{not valid json", subsystem_override="billing")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_non_dict_json() -> None:
    res = process_pre_tool_use_hook('["array"]', subsystem_override="billing")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_no_tool_call() -> None:
    payload = json.dumps({"otherKey": 123})
    res = process_pre_tool_use_hook(payload, subsystem_override="billing")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_no_args() -> None:
    payload = json.dumps({"toolCall": {"name": "run_command"}})
    res = process_pre_tool_use_hook(payload, subsystem_override="billing")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_no_file_target() -> None:
    payload = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "ls"}}})
    res = process_pre_tool_use_hook(payload, subsystem_override="billing")
    assert res["decision"] == "allow"


def test_hook_boundary_guard_valid_file_path(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": str(tmp_path / "src" / "modules" / "billing" / "models.py")},
            }
        }
    )
    res = process_pre_tool_use_hook(payload, subsystem_override="billing", repo_root=tmp_path)
    assert res["decision"] == "allow"


def test_hook_boundary_guard_violation_file_path(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(tmp_path / "src" / "modules" / "telemetry" / "models.py")
                },
            }
        }
    )
    res = process_pre_tool_use_hook(payload, subsystem_override="billing", repo_root=tmp_path)
    assert res["decision"] == "deny"
    assert "PreToolUse Boundary Guard" in res["reason"]


def test_main_cli_allow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/modules/billing/engine.py"},
            }
        }
    )
    monkeypatch.setattr("sys.stdin.read", lambda: payload)
    code = main(["--subsystem", "billing", "--root", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["decision"] == "allow"


def test_main_cli_deny(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "docs/PRD.md"},
            }
        }
    )
    monkeypatch.setattr("sys.stdin.read", lambda: payload)
    code = main(["--subsystem", "billing", "--root", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["decision"] == "deny"
    assert "PreToolUse Boundary Guard" in data["reason"]


def test_runs_as_direct_script_without_import_crash(tmp_path: Path) -> None:
    """Antigravity runs the guard as `python3 scripts/hook_boundary_guard.py`.

    That places scripts/ (not the repo root) on sys.path, which previously crashed
    the module-level `from scripts.check_boundaries import ...` with
    ModuleNotFoundError. A crash yields no decision JSON, so the guard fails open.
    This drives the real invocation (repo root NOT on PYTHONPATH) to lock in the
    sys.path bootstrap and prove the guard actually denies.
    """
    script = REPO_ROOT / "scripts" / "hook_boundary_guard.py"
    payload = json.dumps(
        {"toolCall": {"name": "write_to_file", "args": {"TargetFile": "docs/PRD.md"}}}
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["MAESTRO_ACTIVE_SUBSYSTEM"] = "billing"
    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["decision"] == "deny"
    assert "PreToolUse Boundary Guard" in data["reason"]


def test_hooks_json_matches_antigravity_contract() -> None:
    """hooks.json must match Antigravity's runtime file-edit tool names and wire the guard."""
    cfg = json.loads((REPO_ROOT / "hooks.json").read_text())
    entry = cfg["boundary-guard"]["PreToolUse"][0]
    for tool in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        assert tool in entry["matcher"], f"matcher missing Antigravity tool '{tool}'"
    assert "hook_boundary_guard.py" in entry["hooks"][0]["command"]


def test_plugin_manifest_present_and_named() -> None:
    """plugin.json is the Antigravity plugin manifest and must declare name + description."""
    manifest = json.loads((REPO_ROOT / "plugin.json").read_text())
    assert manifest["name"] == "maestro"
    assert manifest["description"].strip()


def test_hook_boundary_guard_implementer_denied_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that implementer role is mechanically denied from modifying contract tests."""
    monkeypatch.setenv("MAESTRO_ACTIVE_ROLE", "implementer")
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(tmp_path / "tests" / "contract" / "billing" / "test_api.py")
                },
            }
        }
    )
    res = process_pre_tool_use_hook(payload, subsystem_override="billing", repo_root=tmp_path)
    assert res["decision"] == "deny"
    assert "PreToolUse Boundary Guard" in res["reason"]
    assert "role 'implementer'" in res["reason"]


def test_hook_boundary_guard_role_unset_allowed_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that with no role set, contract test edits are allowed (legacy behavior)."""
    monkeypatch.delenv("MAESTRO_ACTIVE_ROLE", raising=False)
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(tmp_path / "tests" / "contract" / "billing" / "test_api.py")
                },
            }
        }
    )
    res = process_pre_tool_use_hook(payload, subsystem_override="billing", repo_root=tmp_path)
    assert res["decision"] == "allow"


def test_hook_boundary_guard_test_author_denied_src(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify that test-author role is mechanically denied from modifying source code."""
    monkeypatch.setenv("MAESTRO_ACTIVE_ROLE", "test-author")
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(tmp_path / "src" / "modules" / "billing" / "invoice.py")
                },
            }
        }
    )
    res = process_pre_tool_use_hook(payload, subsystem_override="billing", repo_root=tmp_path)
    assert res["decision"] == "deny"
    assert "PreToolUse Boundary Guard" in res["reason"]
    assert "role 'test-author'" in res["reason"]


def test_main_cli_with_role_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Verify CLI --role flag passes through to boundary evaluation."""
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "tests/contract/billing/test_contract.py"},
            }
        }
    )
    monkeypatch.setattr("sys.stdin.read", lambda: payload)
    code = main(["--subsystem", "billing", "--role", "implementer", "--root", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["decision"] == "deny"
