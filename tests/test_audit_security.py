"""Unit tests for scripts/audit_security.py ensuring 100% test coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.audit_security import (
    audit_security_file,
    audit_security_text,
    main,
)

VALID_SECURITY_MD = """# Security Architecture & Threat Model Specification

## 1. Security Overview & Scope
* Target Architecture: docs/architecture.md
* Classification: Confidential
* Standards: Google Cloud WAF Security Pillar, OWASP API Top 10

## 2. Trust Boundaries & Data Flow Diagram
```mermaid
flowchart TD
    Client --> Armor[Cloud Armor]
    Armor --> Gateway[API Gateway]
    Gateway --> Service[Core Service]
    Service --> DB[(Firestore)]
    Service --> Secrets[Secret Manager]
```

## 3. STRIDE Threat Analysis Matrix
| ID | Boundary | STRIDE | Threat | Sev | Mitigation | NFR | Verify |
|---|---|---|---|---|---|---|---|
| T-1 | Ingress | Spoofing | Fake token | High | OIDC JWT verify | [NFR-SEC-1] | Integration |
| T-2 | Bus | Tampering | Bad payload | High | TLS 1.3 | [NFR-SEC-2] | Contract |
| T-3 | Audit | Repudiation | Deny act | Med | Audit Logs | [NFR-SEC-3] | Cloud Log |
| T-4 | API | Info Disclosure | Leaks | Med | RFC 7807 | [NFR-SEC-4] | Unit |
| T-5 | Ingress | Denial of Service | Flood | High | Cloud Armor | [NFR-SEC-5] | Armor |
| T-6 | Service | Elevation of Priv | Escalate | High | Custom IAM | [NFR-SEC-6] | IAM audit |

## 4. IAM Least-Privilege Role Matrix
| Subsystem / Service | Dedicated Service Account | Assigned GCP IAM Roles | Resource Scope |
|---|---|---|---|
| API Gateway | sa-gateway@my-proj.iam.gserviceaccount.com | roles/run.invoker | Cloud Run |
| Core Service | sa-core@my-proj.iam.gserviceaccount.com | roles/datastore.user | Firestore |

## 5. Secret Inventory & Cryptographic Controls
| Secret Name | Storage Mechanism | Consumer SA | Encryption Standard | Rotation Schedule |
|---|---|---|---|---|
| db-password | Google Cloud Secret Manager | sa-core | Google KMS CMEK | 90 Days |
| jwt-key | Google Cloud Secret Manager | sa-gateway | Google KMS CMEK | 180 Days |

## 6. OWASP API Top 10 Mitigation Summary
* API1:2023 BOLA: Subsystem validates tenant ownership on all queries.
* API2:2023 Broken Authentication: Centralized OIDC token validation.
* API3:2023 Broken Object Property: Pydantic schemas filter fields.
* API4:2023 Unrestricted Resource Consumption: Cloud Armor rate limits.
"""


def test_audit_security_text_valid() -> None:
    report = audit_security_text(VALID_SECURITY_MD)
    assert report.passed
    assert len(report.violations) == 0
    assert len(report.stride_categories_found) == 6
    assert len(report.service_accounts_found) == 2
    assert len(report.secrets_found) == 2
    assert report.has_mermaid


def test_audit_security_text_empty() -> None:
    report = audit_security_text("")
    assert not report.passed
    assert "empty or too short" in report.violations[0]


def test_audit_security_text_placeholders() -> None:
    bad_md = VALID_SECURITY_MD + "\nSome unresolved <subsystem> text and TODO item."
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("placeholder '<subsystem>'" in v for v in report.violations)
    assert any("placeholder 'TODO'" in v for v in report.violations)


def test_audit_security_text_missing_sections() -> None:
    bad_md = "# Minimal Security\n```mermaid\nflowchart TD\nA-->B\n```\n"
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("Missing required section" in v for v in report.violations)


def test_audit_security_text_missing_mermaid() -> None:
    bad_md = VALID_SECURITY_MD.replace("```mermaid", "```")
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("Missing Mermaid trust boundary" in v for v in report.violations)


def test_audit_security_text_missing_stride_categories() -> None:
    bad_md = VALID_SECURITY_MD.replace("Spoofing", "OtherRisk").replace("Tampering", "OtherRisk")
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("STRIDE Threat Matrix is missing coverage" in v for v in report.violations)


def test_audit_security_text_forbidden_iam_roles() -> None:
    bad_md = VALID_SECURITY_MD.replace("roles/datastore.user", "roles/owner")
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any(
        "Forbidden primitive IAM role detected: 'roles/owner'" in v for v in report.violations
    )

    bad_editor = VALID_SECURITY_MD.replace("roles/datastore.user", "roles/editor")
    report_ed = audit_security_text(bad_editor)
    assert not report_ed.passed
    assert any(
        "Forbidden primitive IAM role detected: 'roles/editor'" in v for v in report_ed.violations
    )


def test_audit_security_text_no_service_accounts() -> None:
    bad_md = VALID_SECURITY_MD.replace(".iam.gserviceaccount.com", ".example.com").replace(
        "sa-", "svc-"
    )
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("No dedicated service accounts found" in v for v in report.violations)


def test_audit_security_text_empty_secret_table() -> None:
    bad_md = VALID_SECURITY_MD.replace(
        "| db-password | Google Cloud Secret Manager | sa-core | Google KMS CMEK | 90 Days |\n"
        "| jwt-key | Google Cloud Secret Manager | sa-gateway | Google KMS CMEK | 180 Days |",
        "",
    )
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any(
        "Secret Inventory table does not contain any cataloged secrets" in v
        for v in report.violations
    )


def test_audit_security_text_missing_secret_section() -> None:
    bad_md = VALID_SECURITY_MD.replace(
        "## 5. Secret Inventory & Cryptographic Controls", "## 5. None"
    )
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("Missing Secret Inventory" in v for v in report.violations)


def test_audit_security_text_missing_owasp_section() -> None:
    bad_md = VALID_SECURITY_MD.replace("## 6. OWASP API Top 10 Mitigation Summary", "## 6. None")
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("Missing OWASP API" in v for v in report.violations)


def test_audit_security_text_weak_owasp() -> None:
    weak_block = (
        "* API1:2023 BOLA: Subsystem validates tenant ownership on all queries.\n"
        "* API2:2023 Broken Authentication: Centralized OIDC token validation.\n"
        "* API3:2023 Broken Object Property: Pydantic schemas filter fields.\n"
        "* API4:2023 Unrestricted Resource Consumption: Cloud Armor rate limits."
    )
    bad_md = VALID_SECURITY_MD.replace(weak_block, "Just general security.")
    report = audit_security_text(bad_md)
    assert not report.passed
    assert any("OWASP API Top 10 section must detail specific" in v for v in report.violations)


def test_audit_security_text_prd_nfr_traceability() -> None:
    prd_text = "# PRD\n* [NFR-SEC-1] Must use OIDC auth\n* [NFR-SEC-2] Must use CMEK\n"
    report_valid = audit_security_text(VALID_SECURITY_MD, prd_text=prd_text)
    assert report_valid.passed

    no_nfr_md = (
        VALID_SECURITY_MD.replace("[NFR-SEC-1]", "None")
        .replace("[NFR-SEC-2]", "None")
        .replace("[NFR-SEC-3]", "None")
        .replace("[NFR-SEC-4]", "None")
        .replace("[NFR-SEC-5]", "None")
        .replace("[NFR-SEC-6]", "None")
    )
    report_no_nfr = audit_security_text(no_nfr_md, prd_text=prd_text)
    assert not report_no_nfr.passed
    assert any("PRD defines security/compliance NFRs" in v for v in report_no_nfr.violations)


def test_audit_security_file_valid(tmp_path: Path) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text(VALID_SECURITY_MD, encoding="utf-8")
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text("# PRD\n* [NFR-SEC-1] Encrypt all data\n", encoding="utf-8")

    report = audit_security_file(sec_file, prd_path=prd_file)
    assert report.passed
    assert report.to_dict()["passed"] is True


def test_audit_security_file_not_found() -> None:
    report = audit_security_file("nonexistent/security.md")
    assert not report.passed
    assert any("File not found" in v for v in report.violations)


def test_audit_security_file_oserror(tmp_path: Path) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text(VALID_SECURITY_MD, encoding="utf-8")

    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        report = audit_security_file(sec_file)
        assert not report.passed
        assert any("Could not read file" in v for v in report.violations)


def test_audit_security_file_unreadable_prd(tmp_path: Path) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text(VALID_SECURITY_MD, encoding="utf-8")
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text("# PRD\n", encoding="utf-8")

    orig_read = Path.read_text

    def mock_read(self: Path, *args: object, **kwargs: object) -> str:
        if str(self).endswith("PRD.md"):
            raise OSError("Unreadable PRD")
        return str(orig_read(self, *args, **kwargs))  # type: ignore[arg-type]

    with patch.object(Path, "read_text", autospec=True, side_effect=mock_read):
        report = audit_security_file(sec_file, prd_path=prd_file)
        assert report.passed


def test_main_cli_success(tmp_path: Path, capsys: object) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text(VALID_SECURITY_MD, encoding="utf-8")

    exit_code = main([str(sec_file)])
    assert exit_code == 0


def test_main_cli_quiet(tmp_path: Path, capsys: object) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text(VALID_SECURITY_MD, encoding="utf-8")

    exit_code = main([str(sec_file), "--quiet"])
    assert exit_code == 0


def test_main_cli_json(tmp_path: Path, capsys: object) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text(VALID_SECURITY_MD, encoding="utf-8")

    exit_code = main([str(sec_file), "--json"])
    assert exit_code == 0


def test_main_cli_failure(tmp_path: Path, capsys: object) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text("# Bad", encoding="utf-8")

    exit_code = main([str(sec_file)])
    assert exit_code == 1


def test_main_cli_failure_json(tmp_path: Path, capsys: object) -> None:
    sec_file = tmp_path / "security.md"
    sec_file.write_text("# Bad", encoding="utf-8")

    exit_code = main([str(sec_file), "--json"])
    assert exit_code == 1
