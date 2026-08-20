"""Unit tests for validate_adrs.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_adrs import (
    main,
    validate_adr_content,
    validate_adr_directory,
    validate_adr_file,
)

SAMPLE_VALID_ADR = """# [ADR-0001] Use Cloud Run for Ingestion Microservices

* **Status**: accepted
* **Deciders**: Lead Architect, Tech Lead
* **Date**: 2026-08-20
* **Superseded by**: N/A
* **Approved-by**: user@example.com

## Context and Problem Statement

The system requires high-throughput telemetry ingestion with spiky traffic patterns.
We need a compute platform that scales to zero while sustaining 10k req/sec.

## Decision Drivers

* PRD NFR-Cost: Budget under $100/mo on idle
* PRD NFR-Scale: Auto-scale from 0 to 50 instances in < 2 seconds
* Operational simplicity: Managed patching and serverless operations

## Considered Options

* **Option 1: Cloud Run (Fully Managed)** - Serverless container execution.
* **Option 2: Google Kubernetes Engine (GKE)** - Dedicated Kubernetes cluster.
* **Option 3: Compute Engine VMs** - Managed Instance Groups.

## Decision Outcome

Chosen option: **Option 1: Cloud Run (Fully Managed)**, because it scales to zero on idle,
meets latency SLOs, and eliminates cluster maintenance overhead.

### Positive Consequences

* Zero idle cost.
* Fast container autoscaling.

### Negative Consequences / Trade-offs

* Maximum request timeout of 60 minutes (acceptable for streaming ingestion).

## Pros and Cons of the Options

### Option 1: Cloud Run (Fully Managed)

* Good, because scales to zero.
* Good, because zero ops burden.
* Bad, because ephemeral filesystem.

### Option 2: GKE

* Good, because highly customizable.
* Bad, because minimum cluster base cost.

## Links & References

* https://cloud.google.com/run/docs
"""

SAMPLE_SUPERSEDED_ADR = """# ADR-0002: Cloud SQL PostgreSQL for Telemetry State

* **Status**: superseded
* **Deciders**: Lead Architect
* **Date**: 2026-08-19
* **Superseded by**: ADR-0003
* **Approved-by**: lead-architect

## Context and Problem Statement

Initial datastore proposal using relational SQL.

## Decision Drivers

* ACID transactions
* SQL familiar tooling

## Considered Options

* **Option 1: Cloud SQL**
* **Option 2: Firestore**

## Decision Outcome

Chosen option: Cloud SQL.

### Positive Consequences

* Strong consistency.

### Negative Consequences / Trade-offs

* Connection limits.

## Pros and Cons of the Options

### Option 1: Cloud SQL

* Good, because relational.
* Bad, because scaling limit.

## Links & References

* Link
"""

SAMPLE_REPLACING_ADR = """# [ADR-0003] Firestore in Datastore Mode for High Write Throughput

* **Status**: accepted
* **Deciders**: Lead Architect
* **Date**: 2026-08-20
* **Superseded by**: N/A
* **Approved-by**: user@example.com

## Context and Problem Statement

High write throughput required.

## Decision Drivers

* Write IOPS scaling
* No connection exhaustion

## Considered Options

* **Option 1: Firestore**
* **Option 2: Bigtable**

## Decision Outcome

Chosen option: Firestore.

### Positive Consequences

* Auto-partitioning.

### Negative Consequences / Trade-offs

* No complex joins.

## Pros and Cons of the Options

### Option 1: Firestore

* Good, because scales infinitely.
* Bad, because limited querying.

## Links & References

* Link
"""


def test_validate_adr_content_valid() -> None:
    res = validate_adr_content(
        SAMPLE_VALID_ADR, filename="0001-cloud-run.md", require_approval=True
    )
    assert res.is_valid is True
    assert res.adr_id == "0001"
    assert res.status == "accepted"
    assert res.approved_by == "user@example.com"
    assert len(res.violations) == 0


def test_validate_adr_content_empty() -> None:
    res = validate_adr_content("", filename="empty.md")
    assert res.is_valid is False
    assert "empty" in res.violations[0].lower()


def test_validate_adr_content_invalid_title() -> None:
    bad_title = SAMPLE_VALID_ADR.replace(
        "# [ADR-0001] Use Cloud Run for Ingestion Microservices", "## Some heading"
    )
    res = validate_adr_content(bad_title)
    assert res.is_valid is False
    assert any("title heading" in v for v in res.violations)


def test_validate_adr_content_missing_status() -> None:
    no_status = SAMPLE_VALID_ADR.replace("* **Status**: accepted", "")
    res = validate_adr_content(no_status)
    assert res.is_valid is False
    assert any("Status" in v for v in res.violations)


def test_validate_adr_content_invalid_status_enum() -> None:
    bad_status = SAMPLE_VALID_ADR.replace("* **Status**: accepted", "* **Status**: unknown_status")
    res = validate_adr_content(bad_status)
    assert res.is_valid is False
    assert any("Invalid ADR Status" in v for v in res.violations)


def test_validate_adr_content_superseded_without_target() -> None:
    bad_superseded = SAMPLE_SUPERSEDED_ADR.replace(
        "* **Superseded by**: ADR-0003", "* **Superseded by**: N/A"
    )
    res = validate_adr_content(bad_superseded)
    assert res.is_valid is False
    assert any("superseded" in v.lower() for v in res.violations)


def test_validate_adr_content_require_approval_missing() -> None:
    no_approval = SAMPLE_VALID_ADR.replace(
        "* **Approved-by**: user@example.com", "* **Approved-by**: TBD"
    )
    res = validate_adr_content(no_approval, require_approval=True)
    assert res.is_valid is False
    assert any("Gate 0.5 sign-off failure" in v for v in res.violations)


def test_validate_adr_content_missing_section() -> None:
    no_drivers = SAMPLE_VALID_ADR.replace("## Decision Drivers", "## Irrelevant Heading")
    res = validate_adr_content(no_drivers)
    assert res.is_valid is False
    assert any("Decision Drivers" in v for v in res.violations)


def test_validate_adr_file_nonexistent(tmp_path: Path) -> None:
    res = validate_adr_file(tmp_path / "nonexistent.md")
    assert res.is_valid is False
    assert "does not exist" in res.violations[0]


def test_validate_adr_file_valid(tmp_path: Path) -> None:
    file_path = tmp_path / "0001-cloud-run.md"
    file_path.write_text(SAMPLE_VALID_ADR, encoding="utf-8")
    res = validate_adr_file(file_path)
    assert res.is_valid is True
    assert res.to_dict()["valid"] is True


def test_validate_adr_directory_nonexistent(tmp_path: Path) -> None:
    report = validate_adr_directory(tmp_path / "missing_dir")
    assert report.is_valid is False
    assert any("does not exist" in v for v in report.directory_violations)


def test_validate_adr_directory_empty(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_adr"
    empty_dir.mkdir()
    report = validate_adr_directory(empty_dir)
    assert report.is_valid is False
    assert any("no markdown" in v for v in report.directory_violations)


def test_validate_adr_directory_valid(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-cloud-run.md").write_text(SAMPLE_VALID_ADR, encoding="utf-8")
    (adr_dir / "0002-cloud-sql.md").write_text(SAMPLE_SUPERSEDED_ADR, encoding="utf-8")
    (adr_dir / "0003-firestore.md").write_text(SAMPLE_REPLACING_ADR, encoding="utf-8")

    report = validate_adr_directory(adr_dir, require_approval=True)
    assert report.is_valid is True
    assert report.adr_count == 3
    assert report.to_dict()["valid"] is True


def test_validate_adr_directory_non_contiguous_sequence(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_gap"
    adr_dir.mkdir()
    (adr_dir / "0002-cloud-sql.md").write_text(SAMPLE_SUPERSEDED_ADR, encoding="utf-8")
    (adr_dir / "0003-firestore.md").write_text(SAMPLE_REPLACING_ADR, encoding="utf-8")

    report = validate_adr_directory(adr_dir)
    assert report.is_valid is False
    assert any("start at 0001" in v for v in report.directory_violations)


def test_validate_adr_directory_dangling_superseded_link(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_dangling"
    adr_dir.mkdir()
    (adr_dir / "0001-cloud-run.md").write_text(SAMPLE_VALID_ADR, encoding="utf-8")
    (adr_dir / "0002-cloud-sql.md").write_text(
        SAMPLE_SUPERSEDED_ADR.replace("ADR-0003", "ADR-0099"), encoding="utf-8"
    )

    report = validate_adr_directory(adr_dir)
    assert report.is_valid is False
    assert any("superseded by 'ADR-0099'" in v for v in report.directory_violations)


def test_validate_adr_directory_with_architecture_file(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_arch"
    adr_dir.mkdir()
    (adr_dir / "0001-cloud-run.md").write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    arch_file = tmp_path / "architecture.md"
    arch_file.write_text(
        """# Architecture
## 3. Frozen Cloud Service Decisions
| Architectural Concern | Service / Component | WAF-Driver Rationale |
|---|---|---|
| Ingestion Compute | Cloud Run | Scalability |
""",
        encoding="utf-8",
    )

    report = validate_adr_directory(adr_dir, architecture_file=arch_file)
    assert report.is_valid is True


def test_validate_adr_directory_with_missing_architecture_file(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_arch"
    adr_dir.mkdir()
    (adr_dir / "0001-cloud-run.md").write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    report = validate_adr_directory(adr_dir, architecture_file=tmp_path / "nonexistent.md")
    assert report.is_valid is False
    assert any("does not exist" in v for v in report.directory_violations)


def test_validate_adr_directory_architecture_without_accepted_adr(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_arch"
    adr_dir.mkdir()
    (adr_dir / "0001-cloud-run.md").write_text(
        SAMPLE_VALID_ADR.replace("* **Status**: accepted", "* **Status**: proposed"),
        encoding="utf-8",
    )

    arch_file = tmp_path / "architecture.md"
    arch_file.write_text(
        """# Architecture
## 3. Frozen Cloud Service Decisions
| Architectural Concern | Service / Component | WAF-Driver Rationale |
|---|---|---|
| Ingestion Compute | Cloud Run | Scalability |
""",
        encoding="utf-8",
    )

    report = validate_adr_directory(adr_dir, architecture_file=arch_file)
    assert report.is_valid is False
    assert any("no ADR has 'Status: accepted'" in v for v in report.directory_violations)


def test_main_cli_single_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file_path = tmp_path / "0001-cloud-run.md"
    file_path.write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    code = main([str(file_path)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True


def test_main_cli_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "0001-cloud-run.md").write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    code = main([str(adr_dir), "--require-approval"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True
    assert data["adr_count"] == 1


def test_validate_adr_content_placeholder_braces() -> None:
    braces_status = SAMPLE_VALID_ADR.replace(
        "* **Approved-by**: user@example.com", "* **Approved-by**: {YOUR_NAME}"
    )
    res = validate_adr_content(braces_status, require_approval=True)
    assert res.is_valid is False
    assert any("Gate 0.5 sign-off failure" in v for v in res.violations)


def test_validate_adr_file_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "0001-cloud-run.md"
    file_path.write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    def mock_read_text(*args: object, **kwargs: object) -> str:
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", mock_read_text)
    res = validate_adr_file(file_path)
    assert res.is_valid is False
    assert "Unable to read ADR file" in res.violations[0]


def test_is_placeholder_value_edges() -> None:
    from scripts.validate_adrs import _is_placeholder_value

    assert _is_placeholder_value(None) is True
    assert _is_placeholder_value("") is True
    assert _is_placeholder_value("   ") is True
    assert _is_placeholder_value("valid-user") is False


def test_validate_adr_directory_architecture_no_decisions_table(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_arch_no_table"
    adr_dir.mkdir()
    (adr_dir / "0001-cloud-run.md").write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    arch_file = tmp_path / "architecture.md"
    arch_file.write_text("# Architecture Document\n\nNo decisions table here.", encoding="utf-8")

    report = validate_adr_directory(adr_dir, architecture_file=arch_file)
    assert report.is_valid is True


def test_validate_adr_directory_non_numeric_id(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr_non_num"
    adr_dir.mkdir()
    bad_id_adr = SAMPLE_VALID_ADR.replace("# [ADR-0001]", "# [ADR-0002]")
    (adr_dir / "0002-cloud-run.md").write_text(bad_id_adr, encoding="utf-8")

    report = validate_adr_directory(adr_dir)
    assert report.is_valid is False
    assert any("start at 0001" in v for v in report.directory_violations)


def test_main_cli_explicit_file_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file_path = tmp_path / "0001-cloud-run.md"
    file_path.write_text(SAMPLE_VALID_ADR, encoding="utf-8")

    code = main(["--file", str(file_path)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True


def test_main_cli_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "0001-bad.md").write_text("# Bad ADR", encoding="utf-8")

    code = main([str(adr_dir)])
    assert code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False
