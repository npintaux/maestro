"""Integration tests for scripts/run_gate_suite.sh."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_run_gate_suite_unknown_stage() -> None:
    res = subprocess.run(
        ["bash", "scripts/run_gate_suite.sh", "unknown-stage"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "Unknown stage" in res.stdout or "Unknown stage" in res.stderr


def test_run_gate_suite_help_or_contract_missing_file() -> None:
    res = subprocess.run(
        ["bash", "scripts/run_gate_suite.sh", "gate-contract", "nonexistent_subsystem"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0


def test_run_gate_suite_from_external_cwd(tmp_path: Path) -> None:
    # Run the script from tmp_path and verify it executes against tmp_path
    repo_root = Path(__file__).resolve().parent.parent
    script_path = (repo_root / "scripts" / "run_gate_suite.sh").resolve()
    res = subprocess.run(
        ["bash", str(script_path), "gate-0"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    # Gate 0 should fail in an empty directory because docs/adr is missing
    assert res.returncode != 0
    output = res.stdout + res.stderr
    assert "Directory does not exist" in output or "docs/adr" in output

