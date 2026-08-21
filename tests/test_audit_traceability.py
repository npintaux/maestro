"""Unit tests for audit_traceability.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_traceability import audit_files, audit_traceability, main

PRD = "US-1 shorten a URL. US-2 view analytics."
ARCH = "Modules: src/modules/link_store/ and src/modules/analytics/."

MATRIX_OK = """
| User Story | Subsystems |
|---|---|
| US-1 | link_store |
| US-2 | link_store, analytics |
"""


def test_valid_matrix_passes() -> None:
    report = audit_traceability(PRD, ARCH, MATRIX_OK)
    assert report.is_valid, report.violations
    assert report.prd_stories == ["US-1", "US-2"]
    assert report.architecture_subsystems == ["analytics", "link_store"]


def test_many_to_many_is_fine() -> None:
    # US-2 spans two subsystems; link_store serves two stories. Both legal.
    report = audit_traceability(PRD, ARCH, MATRIX_OK)
    assert report.is_valid


def test_orphaned_story_fails() -> None:
    matrix = "| US-1 | link_store, analytics |\n"  # US-2 absent entirely
    report = audit_traceability(PRD, ARCH, matrix)
    assert not report.is_valid
    assert any("orphaned story: US-2" in v for v in report.violations)


def test_story_mapped_to_placeholder_is_orphaned() -> None:
    matrix = "| US-1 | link_store, analytics |\n| US-2 | TBD |\n"
    report = audit_traceability(PRD, ARCH, matrix)
    assert not report.is_valid
    assert any("orphaned story: US-2" in v for v in report.violations)


def test_speculative_subsystem_fails() -> None:
    arch = ARCH + " Also src/modules/billing/."
    report = audit_traceability(PRD, arch, MATRIX_OK)
    assert not report.is_valid
    assert any("speculative subsystem: 'billing'" in v for v in report.violations)


def test_dangling_story_reference_fails() -> None:
    matrix = MATRIX_OK + "| US-9 | link_store |\n"
    report = audit_traceability(PRD, ARCH, matrix)
    assert not report.is_valid
    assert any("dangling story: the matrix references US-9" in v for v in report.violations)


def test_unknown_subsystem_reference_fails() -> None:
    matrix = "| US-1 | link_store |\n| US-2 | analytics, ghost_service |\n"
    report = audit_traceability(PRD, ARCH, matrix)
    assert not report.is_valid
    assert any("unknown subsystem: the matrix references 'ghost_service'" in v for v in report.violations)


def test_src_modules_prefix_in_matrix_is_normalized() -> None:
    matrix = "| US-1 | src/modules/link_store |\n| US-2 | src/modules/analytics |\n"
    report = audit_traceability(PRD, ARCH, matrix)
    assert report.is_valid, report.violations


def test_backticked_subsystems_parsed() -> None:
    matrix = "| US-1 | `link_store` |\n| US-2 | `link_store`, `analytics` |\n"
    report = audit_traceability(PRD, ARCH, matrix)
    assert report.is_valid, report.violations


def test_no_prd_stories_fails() -> None:
    report = audit_traceability("no stories here", ARCH, MATRIX_OK)
    assert not report.is_valid
    assert any("declares no User Stories" in v for v in report.violations)


def test_no_subsystems_fails() -> None:
    report = audit_traceability(PRD, "no modules here", MATRIX_OK)
    assert not report.is_valid
    assert any("declares no subsystems" in v for v in report.violations)


def test_empty_matrix_fails() -> None:
    report = audit_traceability(PRD, ARCH, "# Traceability\n\nnothing tabular here\n")
    assert not report.is_valid
    assert any("no story->subsystem rows" in v for v in report.violations)


def test_story_case_insensitive() -> None:
    matrix = "| us-1 | link_store |\n| Us-2 | analytics |\n"
    report = audit_traceability(PRD, ARCH, matrix)
    assert report.is_valid, report.violations


# --------------------------------------------------------------------------- #
# File wrapper + CLI
# --------------------------------------------------------------------------- #


def _write_inputs(root: Path, matrix: str = MATRIX_OK) -> tuple[Path, Path, Path]:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    prd = docs / "PRD.md"
    arch = docs / "architecture.md"
    trace = docs / "traceability.md"
    prd.write_text(PRD)
    arch.write_text(ARCH)
    trace.write_text(matrix)
    return prd, arch, trace


def test_audit_files_missing_input(tmp_path: Path) -> None:
    report = audit_files(tmp_path / "docs" / "PRD.md", tmp_path / "a.md", tmp_path / "t.md")
    assert not report.is_valid
    assert all("required input missing" in v for v in report.violations)


def test_main_cli_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prd, arch, trace = _write_inputs(tmp_path)
    code = main(["--prd", str(prd), "--architecture", str(arch), "--traceability", str(trace)])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_main_cli_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prd, arch, trace = _write_inputs(tmp_path, matrix="| US-1 | link_store |\n")  # US-2 orphaned
    code = main(["--prd", str(prd), "--architecture", str(arch), "--traceability", str(trace)])
    assert code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["valid"] is False
    assert "orphaned story: US-2" in captured.err
