"""Unit tests for the GCP Well-Architected Framework Auditor (scripts/audit_waf_compliance.py)."""

import json
from pathlib import Path

import pytest

from scripts.audit_waf_compliance import (
    audit_architecture_file,
    audit_architecture_text,
    main,
)

FROZEN_DECISIONS_TABLE = """## Frozen Cloud Service Decisions

| Architectural Concern | Chosen GCP Service | Rationale (WAF Driver) |
|---|---|---|
| Compute | Cloud Run | Scale-to-zero serverless (Cost) |
| Datastore | Firestore | Serverless key-value store (System Design) |
| Perimeter | Cloud Armor | Rate limiting and DDoS defense (Security) |
| Secrets | Secret Manager | No plaintext credentials (Security) |
"""


@pytest.fixture
def valid_architecture_markdown() -> str:
    """Fixture providing a complete, compliant architecture.md markdown content."""
    return f"""# System Architecture & Technical Design

## 1. Executive Summary & Topology
This architecture defines the cloud backend deployed on Google Cloud Platform (GCP).

```mermaid
graph TD
    Client --> CloudRun[Cloud Run Service]
    CloudRun --> Firestore[(Firestore)]
    CloudRun --> PubSub[Pub/Sub Event Bus]
```

## 2. Subsystem Macro-Decomposition
The system is decomposed into autonomous subsystems:
- `src/modules/billing/` (Billing & Invoicing)
- `src/modules/orders/` (Order Lifecycle)
- `src/modules/notifications/` (Customer Alerts)

{FROZEN_DECISIONS_TABLE}

## 3. Google Cloud Well-Architected Framework Compliance

### 3.1 System Design
- **Compute**: Cloud Run serverless microservices.
- **Data Storage**: Firestore for entity data and Cloud Storage for documents.
- **Reference**: https://cloud.google.com/architecture/framework/system-design

### 3.2 Operational Excellence
- **Observability**: Structured Cloud Logging, Cloud Monitoring metrics, and Cloud Trace.
- **SLO Targets**: 99.9% availability, error budgets and PagerDuty alerts.
- **Reference**: https://cloud.google.com/architecture/framework/operational-excellence

### 3.3 Security, Privacy, and Compliance
- **Zero Trust & IAM**: Identity-Aware Proxy, Workload Identity, and Secret Manager.
- **Perimeter Defense**: Cloud Armor DDoS protection and WAF rules.
- **Reference**: https://cloud.google.com/architecture/framework/security

### 3.4 Reliability and Disaster Recovery
- **High Availability**: Multi-zone regional deployment with automated failover.
- **Resilience**: Exponential backoff retries, idempotent Pub/Sub consumers, and RTO < 1h.
- **Reference**: https://cloud.google.com/architecture/framework/reliability

### 3.5 Cost Optimization
- **Efficiency**: Auto-scaling down to zero instances on idle.
- **Governance**: Cloud Billing budgets, alerts, and resource tagging.
- **Reference**: https://cloud.google.com/architecture/framework/cost-optimization

### 3.6 Performance Optimization
- **Latency**: Memorystore Redis caching for read-heavy entities.
- **Throughput**: Async Pub/Sub message ingestion and connection pooling.
- **Reference**: https://cloud.google.com/architecture/framework/performance

### 3.7 Sustainability
- **Low-Carbon Regions**: Primary deployment in `europe-west1` (high Carbon Free Energy score).
- **Resource Sizing**: Minimized idle allocations and serverless rightsizing.
- **Reference**: https://cloud.google.com/architecture/framework/sustainability
"""


def _all_pillar_sections(*, with_citations: bool) -> str:
    """Build seven cited (or uncited) pillar sections for focused fixtures."""
    pillars = [
        ("System Design", "system-design", "Cloud Run."),
        ("Operational Excellence", "operational-excellence", "Cloud Logging."),
        ("Security", "security", "Secret Manager."),
        ("Reliability", "reliability", "Multi-zone."),
        ("Cost Optimization", "cost-optimization", "Scale to zero."),
        ("Performance", "performance", "Memorystore caching."),
        ("Sustainability", "sustainability", "europe-west1."),
    ]
    blocks = []
    for name, slug, body in pillars:
        citation = (
            f"https://cloud.google.com/architecture/framework/{slug}\n" if with_citations else ""
        )
        blocks.append(f"## {name}\n{body}\n{citation}")
    return "\n".join(blocks)


def test_audit_architecture_text_valid(valid_architecture_markdown: str) -> None:
    """Verify that a fully compliant architecture passes all rules."""
    report = audit_architecture_text(valid_architecture_markdown)
    assert report.is_valid is True
    assert report.violations == []
    assert len(report.pillars_missing) == 0
    assert len(report.pillars_uncited) == 0
    assert len(report.pillars_found) == 7
    assert len(report.subsystems_found) >= 3
    assert len(report.gcp_services_mentioned) >= 4
    assert report.docs_citations_count >= 7
    assert "Cloud Run" in report.frozen_services
    assert "Firestore" in report.frozen_services


def test_audit_architecture_missing_pillars() -> None:
    """Verify that missing pillar sections are correctly flagged as invalid."""
    incomplete_md = """# Architecture
## System Design
Cloud Run compute.
https://cloud.google.com/architecture/framework/system-design
"""
    report = audit_architecture_text(incomplete_md)
    assert report.is_valid is False
    assert "security" in report.pillars_missing
    assert "reliability" in report.pillars_missing
    assert "cost_optimization" in report.pillars_missing
    assert "operational_excellence" in report.pillars_missing
    assert "performance" in report.pillars_missing
    assert "sustainability" in report.pillars_missing


def test_audit_architecture_file_valid(
    tmp_path: Path,
    valid_architecture_markdown: str,
) -> None:
    """Verify auditing an actual file on disk."""
    arch_file = tmp_path / "architecture.md"
    arch_file.write_text(valid_architecture_markdown, encoding="utf-8")

    report = audit_architecture_file(arch_file)
    assert report.is_valid is True
    assert report.file_path == str(arch_file)


def test_audit_architecture_file_not_found(tmp_path: Path) -> None:
    """Verify error handling when file does not exist."""
    missing_file = tmp_path / "non_existent.md"
    report = audit_architecture_file(missing_file)
    assert report.is_valid is False
    assert "File not found" in str(report.violations)


def test_audit_architecture_empty_file(tmp_path: Path) -> None:
    """Verify error handling when file is empty."""
    empty_file = tmp_path / "empty.md"
    empty_file.write_text("", encoding="utf-8")
    report = audit_architecture_file(empty_file)
    assert report.is_valid is False
    assert "Document is empty" in str(report.violations)


def test_audit_architecture_pillars_uncited() -> None:
    """Verify violation when 7 pillar sections exist but carry no framework citations."""
    no_citations_md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=False)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + FROZEN_DECISIONS_TABLE
    )
    report = audit_architecture_text(no_citations_md)
    assert report.is_valid is False
    assert len(report.pillars_uncited) == 7
    assert any("documentation citation" in v for v in report.violations)


def test_audit_architecture_missing_subsystems() -> None:
    """Verify violation when no subsystem module paths are defined."""
    no_subsystems_md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n"
        + FROZEN_DECISIONS_TABLE
    )
    report = audit_architecture_text(no_subsystems_md)
    assert report.is_valid is False
    assert any("subsystem" in v.lower() for v in report.violations)


def test_audit_missing_frozen_decisions_section() -> None:
    """Verify violation when the frozen service decisions section is absent."""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("Frozen Cloud Service Decisions" in v for v in report.violations)
    assert report.frozen_services == []


def test_audit_frozen_decisions_too_few_services() -> None:
    """Verify violation when fewer than the minimum number of services are frozen."""
    thin_table = """## Frozen Cloud Service Decisions

| Concern | Chosen GCP Service | Rationale |
|---|---|---|
| Compute | Cloud Run | Serverless |
| Datastore | Firestore | Key-value |
"""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + thin_table
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("at least 3 concrete GCP services" in v for v in report.violations)


def test_audit_frozen_decisions_unrecognized_service() -> None:
    """Verify violation when a frozen decision names an unrecognized/ambiguous service."""
    bad_table = """## Frozen Cloud Service Decisions

| Concern | Chosen GCP Service | Rationale |
|---|---|---|
| Compute | Cloud Run | Serverless |
| Datastore | Firestore | Key-value |
| Cache | SomeMagicCache | Fast |
"""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + bad_table
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("unrecognized/ambiguous GCP service" in v for v in report.violations)
    assert "SomeMagicCache" in str(report.violations)


def test_audit_frozen_decisions_missing_service_column() -> None:
    """Verify violation when the frozen table lacks a Service column."""
    bad_table = """## Frozen Cloud Service Decisions

| Concern | Rationale |
|---|---|
| Compute | Serverless |
"""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + bad_table
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("column header containing 'Service'" in v for v in report.violations)
    assert report.frozen_services == []


def test_audit_frozen_decisions_missing_rationale_column() -> None:
    """Verify violation when the frozen table lacks a rationale/WAF-driver column."""
    bad_table = """## Frozen Cloud Service Decisions

| Concern | Chosen GCP Service |
|---|---|
| Compute | Cloud Run |
| Datastore | Firestore |
| Perimeter | Cloud Armor |
"""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + bad_table
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("rationale/WAF-driver column" in v for v in report.violations)


def test_audit_frozen_decisions_missing_rationale_value() -> None:
    """Verify violation when an individual frozen decision has an empty rationale cell."""
    bad_table = """## Frozen Cloud Service Decisions

| Concern | Chosen GCP Service | Rationale |
|---|---|---|
| Compute | Cloud Run | Serverless |
| Datastore | Firestore | Key-value |
| Perimeter | Cloud Armor | |
"""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + bad_table
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("missing a rationale/WAF driver" in v for v in report.violations)


def test_audit_frozen_decisions_table_too_short() -> None:
    """Verify violation when the frozen section has no complete table."""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + "## Frozen Cloud Service Decisions\nWe will decide the services later.\n"
    )
    report = audit_architecture_text(md)
    assert report.is_valid is False
    assert any("markdown table with a header" in v for v in report.violations)


def test_audit_frozen_decisions_ignores_short_and_empty_rows() -> None:
    """Verify that malformed short rows and empty service cells are skipped, not counted."""
    table = """## Frozen Cloud Service Decisions

| Concern | Chosen GCP Service | Rationale |
|---|---|---|
| Compute | Cloud Run | Serverless |
| Datastore | Firestore | Key-value |
| Perimeter | Cloud Armor | Rate limiting |
| Truncated row
|  |  |  |
"""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + table
    )
    report = audit_architecture_text(md)
    assert report.is_valid is True
    assert report.frozen_services == ["Cloud Armor", "Cloud Run", "Firestore"]


def test_audit_excludes_services_only_mentioned_as_rejected() -> None:
    """Verify a service mentioned solely in an exclusion context is not reported as selected."""
    md = (
        "# Architecture\n"
        + _all_pillar_sections(with_citations=True)
        + "\n## Subsystems\n`src/modules/core/`\n"
        + FROZEN_DECISIONS_TABLE
        + "\n## Notes\nWe deliberately excluded Cloud Spanner to protect the budget.\n"
    )
    report = audit_architecture_text(md)
    assert report.is_valid is True
    assert "Cloud Spanner" not in report.gcp_services_mentioned
    # Firestore appears in the frozen table (non-exclusion), so it remains selected.
    assert "Firestore" in report.gcp_services_mentioned


def test_main_cli_success(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    valid_architecture_markdown: str,
) -> None:
    """Verify CLI exit code 0 on compliant architecture."""
    arch_file = tmp_path / "architecture.md"
    arch_file.write_text(valid_architecture_markdown, encoding="utf-8")

    exit_code = main([str(arch_file)])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True


def test_main_cli_failure(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI exit code 1 on non-compliant architecture."""
    arch_file = tmp_path / "architecture.md"
    arch_file.write_text("# Incomplete", encoding="utf-8")

    exit_code = main([str(arch_file)])
    assert exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False


def test_main_cli_missing_arg() -> None:
    """Verify CLI error on missing argument."""
    with pytest.raises(SystemExit):
        main([])
