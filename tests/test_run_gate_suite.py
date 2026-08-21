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


def test_run_gate_suite_gate_ui_missing_file() -> None:
    res = subprocess.run(
        ["bash", "scripts/run_gate_suite.sh", "gate-ui", "nonexistent_subsystem"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0
    assert "ui-spec file not found" in res.stdout + res.stderr


def test_run_gate_suite_gate_ui_all_no_specs(tmp_path: Path) -> None:
    # In a directory with an empty src/modules, gate-ui finds no ui-spec.json and passes cleanly.
    (tmp_path / "src" / "modules").mkdir(parents=True)
    repo_root = Path(__file__).resolve().parent.parent
    script_path = (repo_root / "scripts" / "run_gate_suite.sh").resolve()
    res = subprocess.run(
        ["bash", str(script_path), "gate-ui"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "No subsystems with ui-spec.json" in res.stdout


def test_run_gate_suite_gate_frontend_missing_dir() -> None:
    res = subprocess.run(
        ["bash", "scripts/run_gate_suite.sh", "gate-frontend", "nonexistent_subsystem"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0
    assert "front-end directory not found" in res.stdout + res.stderr


def test_run_gate_suite_gate_frontend_all_no_frontends(tmp_path: Path) -> None:
    # With an empty src/modules, gate-frontend finds no frontend/ dir and passes cleanly.
    (tmp_path / "src" / "modules").mkdir(parents=True)
    repo_root = Path(__file__).resolve().parent.parent
    script_path = (repo_root / "scripts" / "run_gate_suite.sh").resolve()
    res = subprocess.run(
        ["bash", str(script_path), "gate-frontend"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "No subsystems with a frontend/ directory" in res.stdout


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

