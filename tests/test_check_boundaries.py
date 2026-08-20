"""Unit tests for the Directory Boundary Guard (scripts/check_boundaries.py)."""

import json
from pathlib import Path

import pytest

from scripts.check_boundaries import (
    check_boundary,
    check_paths_boundary,
    check_tool_input,
    main,
)


def test_valid_subsystem_src_path() -> None:
    """Verify that a path within the assigned subsystem source folder passes."""
    result = check_boundary(
        subsystem="billing",
        target_path="src/modules/billing/domain/invoice.py",
        repo_root="/workspace",
    )
    assert result.is_valid is True
    assert result.violation is None


def test_valid_subsystem_nested_src_path() -> None:
    """Verify that deeply nested paths within the subsystem pass."""
    result = check_boundary(
        subsystem="order_processing",
        target_path="src/modules/order_processing/infrastructure/repositories/order_repo.py",
        repo_root="/workspace",
    )
    assert result.is_valid is True
    assert result.violation is None


def test_valid_subsystem_test_path() -> None:
    """Verify that test paths belonging to the assigned subsystem pass."""
    result = check_boundary(
        subsystem="billing",
        target_path="tests/unit/billing/test_invoice.py",
        repo_root="/workspace",
    )
    assert result.is_valid is True

    integration_result = check_boundary(
        subsystem="billing",
        target_path="tests/integration/billing/test_payment_gateway.py",
        repo_root="/workspace",
    )
    assert integration_result.is_valid is True


def test_violation_different_subsystem_path() -> None:
    """Verify that targeting another subsystem fails with a clear violation."""
    result = check_boundary(
        subsystem="billing",
        target_path="src/modules/auth/domain/user.py",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert result.violation is not None
    assert "outside assigned subsystem boundary" in result.violation


def test_violation_global_contract_files() -> None:
    """Verify that worker subagents cannot modify global architecture or PRD files."""
    for forbidden_file in [
        "docs/PRD.md",
        "architecture.md",
        "openapi.yaml",
        "scripts/check_boundaries.py",
        ".github/workflows/ci.yml",
    ]:
        result = check_boundary(
            subsystem="billing",
            target_path=forbidden_file,
            repo_root="/workspace",
        )
        assert result.is_valid is False
        assert result.violation is not None


def test_violation_path_traversal() -> None:
    """Verify that directory traversal sequences cannot escape the subsystem."""
    result = check_boundary(
        subsystem="billing",
        target_path="src/modules/billing/../../auth/service.py",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert result.violation is not None


def test_violation_outside_repo_root_absolute() -> None:
    """Verify that absolute paths outside repo root fail validation."""
    result = check_boundary(
        subsystem="billing",
        target_path="/etc/passwd",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert "outside repository root" in str(result.violation)


def test_violation_outside_repo_root_relative() -> None:
    """Verify that relative paths escaping repo root fail validation."""
    result = check_boundary(
        subsystem="billing",
        target_path="../../../etc/passwd",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert "directory traversal outside repository root" in str(result.violation)


def test_check_paths_boundary_all_valid() -> None:
    """Verify multi-path check passes when all paths are inside boundary."""
    paths = [
        "src/modules/billing/domain/invoice.py",
        "src/modules/billing/application/create_invoice.py",
        "tests/unit/billing/test_invoice.py",
    ]
    results = check_paths_boundary(
        subsystem="billing",
        target_paths=paths,
        repo_root="/workspace",
    )
    assert all(r.is_valid for r in results)


def test_check_paths_boundary_with_one_violation() -> None:
    """Verify multi-path check identifies individual violations."""
    paths = [
        "src/modules/billing/domain/invoice.py",
        "src/modules/auth/domain/user.py",
    ]
    results = check_paths_boundary(
        subsystem="billing",
        target_paths=paths,
        repo_root="/workspace",
    )
    assert results[0].is_valid is True
    assert results[1].is_valid is False


def test_check_tool_input_valid() -> None:
    """Verify PreToolUse hook payload validation for a valid TargetFile."""
    payload = json.dumps({"TargetFile": "/workspace/src/modules/billing/model.py"})
    result = check_tool_input(
        subsystem="billing",
        tool_input_json=payload,
        repo_root="/workspace",
    )
    assert result.is_valid is True


def test_check_tool_input_violation() -> None:
    """Verify PreToolUse hook payload validation for an invalid TargetFile."""
    payload = json.dumps({"TargetFile": "/workspace/src/modules/auth/model.py"})
    result = check_tool_input(
        subsystem="billing",
        tool_input_json=payload,
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert result.violation is not None


def test_check_tool_input_no_target_file() -> None:
    """Verify tool input with no recognized file field passes gracefully."""
    payload = json.dumps({"CommandLine": "pytest"})
    result = check_tool_input(
        subsystem="billing",
        tool_input_json=payload,
        repo_root="/workspace",
    )
    assert result.is_valid is True


def test_check_tool_input_non_dict_json() -> None:
    """Verify tool input containing a non-dict JSON passes gracefully."""
    result = check_tool_input(
        subsystem="billing",
        tool_input_json="[1, 2, 3]",
        repo_root="/workspace",
    )
    assert result.is_valid is True


def test_check_tool_input_invalid_json() -> None:
    """Verify tool input with invalid JSON returns a violation."""
    result = check_tool_input(
        subsystem="billing",
        tool_input_json="not-a-json",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert "Invalid JSON" in str(result.violation)


def test_empty_subsystem_error() -> None:
    """Verify that an empty subsystem parameter raises ValueError."""
    with pytest.raises(ValueError, match="Subsystem name cannot be empty"):
        check_boundary(subsystem="", target_path="src/modules/billing/model.py")


def test_main_cli_success(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI exit code 0 and JSON output on valid boundary check."""
    exit_code = main(
        [
            "--subsystem",
            "billing",
            "--path",
            "src/modules/billing/service.py",
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True


def test_main_cli_multiple_paths(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI exit code 0 on multiple valid paths."""
    exit_code = main(
        [
            "--subsystem",
            "billing",
            "--paths",
            "src/modules/billing/service.py",
            "tests/unit/billing/test_service.py",
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True


def test_main_cli_violation(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI exit code 1 and error JSON output on boundary violation."""
    exit_code = main(
        [
            "--subsystem",
            "billing",
            "--path",
            "src/modules/auth/service.py",
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False
    assert "outside assigned subsystem boundary" in data["violation"]


def test_main_cli_tool_input(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI with --tool-input payload."""
    payload = json.dumps({"TargetFile": str(tmp_path / "src/modules/billing/repo.py")})
    exit_code = main(
        [
            "--subsystem",
            "billing",
            "--tool-input",
            payload,
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True


def test_main_cli_no_targets(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify CLI returns exit code 2 when no target path or tool input is provided."""
    exit_code = main(["--subsystem", "billing"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Must provide --path, --paths, or --tool-input" in captured.err


def test_role_test_author_allowed() -> None:
    """Verify test-author can write contract and behavioral test files."""
    for path in [
        "tests/contract/billing/test_contract.py",
        "tests/behavioral/billing/test_behavioral.py",
    ]:
        result = check_boundary(
            subsystem="billing",
            target_path=path,
            role="test-author",
            repo_root="/workspace",
        )
        assert result.is_valid is True
        assert result.role == "test-author"


def test_role_test_author_blocked_from_src() -> None:
    """Verify test-author is physically blocked from modifying source code."""
    result = check_boundary(
        subsystem="billing",
        target_path="src/modules/billing/domain/invoice.py",
        role="test-author",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert result.violation is not None
    assert "outside assigned subsystem boundary" in result.violation
    assert "role 'test-author'" in result.violation


def test_role_implementer_allowed() -> None:
    """Verify implementer can write source code and unit/integration tests."""
    for path in [
        "src/modules/billing/domain/invoice.py",
        "tests/unit/billing/test_invoice.py",
        "tests/integration/billing/test_db.py",
    ]:
        result = check_boundary(
            subsystem="billing",
            target_path=path,
            role="implementer",
            repo_root="/workspace",
        )
        assert result.is_valid is True
        assert result.role == "implementer"


def test_role_implementer_blocked_from_contract() -> None:
    """Verify implementer is physically blocked from mutating contract and behavioral tests."""
    for forbidden_path in [
        "tests/contract/billing/test_contract.py",
        "tests/behavioral/billing/test_behavioral.py",
    ]:
        result = check_boundary(
            subsystem="billing",
            target_path=forbidden_path,
            role="implementer",
            repo_root="/workspace",
        )
        assert result.is_valid is False
        assert result.violation is not None
        assert "outside assigned subsystem boundary" in result.violation
        assert "role 'implementer'" in result.violation


def test_unknown_role_fail_closed() -> None:
    """Verify an unknown non-empty role fails closed on all write attempts."""
    result = check_boundary(
        subsystem="billing",
        target_path="src/modules/billing/service.py",
        role="intruder",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert result.violation is not None
    assert "Unknown or unauthorized role 'intruder'" in result.violation


def test_role_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify role resolution respects MAESTRO_ACTIVE_ROLE environment variable."""
    monkeypatch.setenv("MAESTRO_ACTIVE_ROLE", "implementer")
    result = check_boundary(
        subsystem="billing",
        target_path="tests/contract/billing/test_contract.py",
        repo_root="/workspace",
    )
    assert result.is_valid is False
    assert result.role == "implementer"


def test_main_cli_with_role(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI --role flag enforcement."""
    exit_code = main(
        [
            "--subsystem",
            "billing",
            "--role",
            "implementer",
            "--path",
            "tests/contract/billing/test_contract.py",
            "--root",
            str(tmp_path),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False
    assert data["role"] == "implementer"
