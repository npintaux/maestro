"""Unit tests for verify_red_suite.py (RED-Lock Validator)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_red_suite import check_red_lock, lock_red_suite, main


def _create_failing_test(test_dir: Path, filename: str = "test_feature.py") -> Path:
    """Create a minimal failing test file."""
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / filename
    test_file.write_text(
        "def test_failing_criterion():\n    assert False, 'Not implemented yet'\n",
        encoding="utf-8",
    )
    return test_file


def _create_passing_test(test_dir: Path, filename: str = "test_feature.py") -> Path:
    """Create a minimal passing test file."""
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / filename
    test_file.write_text("def test_passing():\n    assert True\n", encoding="utf-8")
    return test_file


def test_lock_missing_test_files_fails(tmp_path: Path) -> None:
    """Verify lock fails when no orthogonal test files exist."""
    exit_code, report = lock_red_suite(
        subsystem="billing",
        state_dir=tmp_path / ".maestro" / "red_lock",
        repo_root=tmp_path,
    )
    assert exit_code == 1
    assert report["valid"] is False
    assert "No orthogonal test files found" in report["error"]


def test_lock_green_suite_fails(tmp_path: Path) -> None:
    """Verify lock fails if pytest exits 0 (suite is not RED)."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    _create_passing_test(contract_dir)

    exit_code, report = lock_red_suite(
        subsystem="billing",
        state_dir=tmp_path / ".maestro" / "red_lock",
        repo_root=tmp_path,
    )
    assert exit_code == 1
    assert report["valid"] is False
    assert "Orthogonal test suite is NOT RED" in report["error"]


def test_lock_genuinely_red_suite_succeeds(tmp_path: Path) -> None:
    """Verify lock succeeds and creates manifest when pytest fails (RED state)."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    behavioral_dir = tmp_path / "tests" / "behavioral" / "billing"
    _create_failing_test(contract_dir, "test_contract.py")
    _create_failing_test(behavioral_dir, "test_behavioral.py")

    state_dir = tmp_path / ".maestro" / "red_lock"
    exit_code, report = lock_red_suite(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert exit_code == 0
    assert report["valid"] is True
    assert report["locked_files_count"] == 2

    manifest_file = state_dir / "billing.json"
    assert manifest_file.is_file()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["subsystem"] == "billing"
    assert "tests/contract/billing/test_contract.py" in manifest_data["files"]
    assert "tests/behavioral/billing/test_behavioral.py" in manifest_data["files"]


def test_lock_pytest_execution_error(tmp_path: Path) -> None:
    """Verify lock handles pytest execution failure cleanly."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    _create_failing_test(contract_dir)

    exit_code, report = lock_red_suite(
        subsystem="billing",
        state_dir=tmp_path / ".maestro" / "red_lock",
        repo_root=tmp_path,
        pytest_runner=["nonexistent_pytest_binary_xyz"],
    )
    assert exit_code == 2
    assert report["valid"] is False
    assert "Failed to execute pytest runner" in report["error"]


def test_check_missing_manifest_fails(tmp_path: Path) -> None:
    """Verify check fails when manifest does not exist."""
    exit_code, report = check_red_lock(
        subsystem="billing",
        state_dir=tmp_path / ".maestro" / "red_lock",
        repo_root=tmp_path,
    )
    assert exit_code == 1
    assert report["valid"] is False
    assert "RED lock manifest missing" in report["error"]


def test_check_corrupted_manifest_fails(tmp_path: Path) -> None:
    """Verify check fails when manifest contains invalid JSON."""
    state_dir = tmp_path / ".maestro" / "red_lock"
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = state_dir / "billing.json"
    manifest_file.write_text("{not valid json", encoding="utf-8")

    exit_code, report = check_red_lock(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert exit_code == 1
    assert report["valid"] is False
    assert "Corrupted RED lock manifest" in report["error"]


def test_check_happy_path(tmp_path: Path) -> None:
    """Verify check passes when locked files match the manifest exactly."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    _create_failing_test(contract_dir, "test_contract.py")

    state_dir = tmp_path / ".maestro" / "red_lock"
    lock_code, _ = lock_red_suite(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert lock_code == 0

    check_code, report = check_red_lock(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert check_code == 0
    assert report["valid"] is True
    assert report["locked_files_count"] == 1


def test_check_tampered_file_fails(tmp_path: Path) -> None:
    """Verify check detects modified bytes in a locked test file."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    test_file = _create_failing_test(contract_dir, "test_contract.py")

    state_dir = tmp_path / ".maestro" / "red_lock"
    lock_red_suite(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )

    # Tamper with the locked file
    test_file.write_text("def test_tampered(): pass\n", encoding="utf-8")

    check_code, report = check_red_lock(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert check_code == 1
    assert report["valid"] is False
    assert "tests/contract/billing/test_contract.py" in report["tampered_files"]


def test_check_removed_file_fails(tmp_path: Path) -> None:
    """Verify check detects deletion of a locked test file."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    test_file = _create_failing_test(contract_dir, "test_contract.py")

    state_dir = tmp_path / ".maestro" / "red_lock"
    lock_red_suite(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )

    # Delete the locked file
    test_file.unlink()

    check_code, report = check_red_lock(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert check_code == 1
    assert report["valid"] is False
    assert "tests/contract/billing/test_contract.py" in report["removed_files"]


def test_check_added_file_fails(tmp_path: Path) -> None:
    """Verify check detects unauthorized addition of test files under locked directories."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    _create_failing_test(contract_dir, "test_contract.py")

    state_dir = tmp_path / ".maestro" / "red_lock"
    lock_red_suite(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )

    # Add new unauthorized file
    _create_failing_test(contract_dir, "test_unauthorized_extra.py")

    check_code, report = check_red_lock(
        subsystem="billing",
        state_dir=state_dir,
        repo_root=tmp_path,
    )
    assert check_code == 1
    assert report["valid"] is False
    assert "tests/contract/billing/test_unauthorized_extra.py" in report["added_files"]


def test_cli_lock_and_check(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI lock and check subcommands."""
    contract_dir = tmp_path / "tests" / "contract" / "billing"
    _create_failing_test(contract_dir, "test_contract.py")
    state_dir = tmp_path / ".maestro" / "red_lock"

    # 1. CLI Lock
    exit_lock = main(
        [
            "lock",
            "--subsystem",
            "billing",
            "--state-dir",
            str(state_dir),
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_lock == 0
    captured_lock = capsys.readouterr()
    data_lock = json.loads(captured_lock.out)
    assert data_lock["valid"] is True

    # 2. CLI Check
    exit_check = main(
        [
            "check",
            "--subsystem",
            "billing",
            "--state-dir",
            str(state_dir),
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_check == 0
    captured_check = capsys.readouterr()
    data_check = json.loads(captured_check.out)
    assert data_check["valid"] is True
