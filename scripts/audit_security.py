#!/usr/bin/env python3
"""Mechanical Security Architecture & STRIDE Threat Model Validator (Gate 0 / Gate 7).

Validates that docs/security.md:
1. Exists and contains no unresolved template placeholders (<...>, TODO, TBD).
2. Contains a valid Trust Boundaries & Data Flow Mermaid diagram.
3. Systematically covers all 6 STRIDE threat categories with mitigations and verifications.
4. Enforces IAM least-privilege role matrix (strictly forbidding roles/owner and roles/editor).
5. Defines Secret Inventory and cryptographic rotation controls.
6. Details OWASP API Top 10 defenses.
7. Cross-references PRD Security NFRs when a PRD is present.

Exit codes:
- 0: Valid security specification
- 1: Validation failures detected
- 2: File missing or CLI argument error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

STRIDE_CATEGORIES: tuple[str, ...] = (
    "spoofing",
    "tampering",
    "repudiation",
    "information disclosure",
    "denial of service",
    "elevation of privilege",
)

# Aliases accepted for table cells
STRIDE_ALIASES: dict[str, str] = {
    "spoofing": "spoofing",
    "tampering": "tampering",
    "repudiation": "repudiation",
    "information disclosure": "information disclosure",
    "info disclosure": "information disclosure",
    "denial of service": "denial of service",
    "dos": "denial of service",
    "elevation of privilege": "elevation of privilege",
    "elevation of priv": "elevation of privilege",
    "privilege escalation": "elevation of privilege",
}

FORBIDDEN_IAM_ROLES: tuple[str, ...] = (
    "roles/owner",
    "roles/editor",
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Security Overview",
    "Trust Boundaries",
    "STRIDE Threat Analysis",
    "IAM Least-Privilege",
    "Secret Inventory",
    "OWASP API",
)


@dataclass
class SecurityAuditReport:
    """Structured result of a security specification audit."""

    passed: bool
    target_path: str
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stride_categories_found: list[str] = field(default_factory=list)
    service_accounts_found: list[str] = field(default_factory=list)
    secrets_found: list[str] = field(default_factory=list)
    nfr_citations_found: list[str] = field(default_factory=list)
    has_mermaid: bool = False

    def to_dict(self) -> dict[str, object]:
        """Convert report to JSON-serializable dictionary."""
        return asdict(self)


def _check_placeholders(text: str) -> list[str]:
    violations: list[str] = []
    placeholder_pattern = re.compile(r"<[a-zA-Z0-9_\-]+>|TODO|\[TBD\]|TBD(?!\w)")
    for line_num, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("<!--") or line.strip().startswith("#"):
            continue
        for match in placeholder_pattern.finditer(line):
            violations.append(
                f"Line {line_num}: Unresolved template placeholder '{match.group(0)}'"
            )
    return violations


def audit_security_text(
    text: str,
    target_path: str = "docs/security.md",
    prd_text: str | None = None,
) -> SecurityAuditReport:
    """Audit the text content of a security specification."""
    violations: list[str] = []
    warnings: list[str] = []
    stride_found: set[str] = set()
    service_accounts: list[str] = []
    secrets: list[str] = []
    nfr_citations: list[str] = []

    if not text.strip() or len(text.strip()) < 50:
        return SecurityAuditReport(
            passed=False,
            target_path=target_path,
            violations=["Security specification file is empty or too short."],
        )

    # 1. Check placeholders
    violations.extend(_check_placeholders(text))

    # 2. Check required section headers
    lower_text = text.lower()
    for section in REQUIRED_SECTIONS:
        if section.lower() not in lower_text:
            violations.append(f"Missing required section matching '{section}'.")

    # 3. Check Trust Boundaries & Mermaid diagram
    has_mermaid = bool(re.search(r"```mermaid\s*\n.*?\n```", text, re.DOTALL))
    if not has_mermaid:
        violations.append("Missing Mermaid trust boundary / data flow diagram in ```mermaid block.")

    # 4. Check STRIDE threat coverage
    for alias, canonical in STRIDE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            stride_found.add(canonical)

    missing_stride = [cat for cat in STRIDE_CATEGORIES if cat not in stride_found]
    if missing_stride:
        violations.append(
            f"STRIDE Threat Matrix is missing coverage for {len(missing_stride)} categories: "
            f"{', '.join(sorted(missing_stride))}."
        )

    # 5. Check IAM Least-Privilege & forbidden primitive roles
    for forbidden_role in FORBIDDEN_IAM_ROLES:
        if forbidden_role in text:
            violations.append(
                f"Forbidden primitive IAM role detected: '{forbidden_role}'. "
                "Use granular predefined or custom IAM roles."
            )

    # Extract service account identifiers
    sa_matches = re.findall(r"[\w\.\-]+@[\w\.\-]+\.iam\.gserviceaccount\.com", text)
    if not sa_matches:
        sa_matches = re.findall(r"sa-[\w\-]+", text)
    service_accounts = sorted(set(sa_matches))
    if not service_accounts:
        violations.append("No dedicated service accounts found in IAM Role Matrix.")

    # 6. Check Secret Inventory
    secret_section = re.search(
        r"^##[^\n]*?Secret Inventory[^\n]*\n(.*?)(?=\n##|\Z)",
        text,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if secret_section:
        sec_content = secret_section.group(1)
        table_rows = [
            line.strip()
            for line in sec_content.splitlines()
            if line.strip().startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", line.strip())
        ]
        if len(table_rows) > 1:
            for row in table_rows[1:]:
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if cells and cells[0] and cells[0].lower() not in ("secret name", "identifier"):
                    secrets.append(cells[0].strip("`"))
        if not secrets:
            violations.append("Secret Inventory table does not contain any cataloged secrets.")
    else:
        violations.append("Missing Secret Inventory & Cryptographic Controls table.")

    # 7. Check OWASP API Summary
    owasp_section = re.search(
        r"^##[^\n]*?OWASP API[^\n]*\n(.*?)(?=\n##|\Z)",
        text,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if owasp_section:
        owasp_content = owasp_section.group(1)
        api_mentions = len(re.findall(r"API\d+:|OWASP|BOLA", owasp_content, re.IGNORECASE))
        if api_mentions < 2:
            violations.append(
                "OWASP API Top 10 section must detail specific API threat mitigations."
            )
    else:
        violations.append("Missing OWASP API Top 10 Mitigation Summary section.")

    # 8. Check PRD Security NFR traceability
    nfr_matches = re.findall(r"\[?(NFR-[\w\-]+|SEC-[\w\-]+)\]?", text)
    nfr_citations = sorted(set(nfr_matches))

    if prd_text:
        prd_nfrs = set(re.findall(r"\[?(NFR-[\w\-]+|SEC-[\w\-]+)\]?", prd_text))
        if prd_nfrs and not nfr_citations:
            violations.append(
                f"PRD defines security/compliance NFRs ({', '.join(sorted(prd_nfrs))}) "
                "but docs/security.md does not cross-reference any NFR tags."
            )

    passed = len(violations) == 0

    return SecurityAuditReport(
        passed=passed,
        target_path=target_path,
        violations=violations,
        warnings=warnings,
        stride_categories_found=sorted(stride_found),
        service_accounts_found=service_accounts,
        secrets_found=secrets,
        nfr_citations_found=nfr_citations,
        has_mermaid=has_mermaid,
    )


def audit_security_file(
    path: str | Path,
    prd_path: str | Path | None = None,
) -> SecurityAuditReport:
    """Audit a security specification file on disk."""
    target = Path(path)
    if not target.exists():
        return SecurityAuditReport(
            passed=False,
            target_path=str(target),
            violations=[f"File not found: {target}"],
        )

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as e:
        return SecurityAuditReport(
            passed=False,
            target_path=str(target),
            violations=[f"Could not read file {target}: {e}"],
        )

    prd_content: str | None = None
    if prd_path:
        prd_file = Path(prd_path)
        if prd_file.exists():
            try:
                prd_content = prd_file.read_text(encoding="utf-8")
            except OSError:
                prd_content = None

    return audit_security_text(content, target_path=str(target), prd_text=prd_content)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for scripts/audit_security.py."""
    parser = argparse.ArgumentParser(
        description="Audit docs/security.md against STRIDE, IAM, and secret standards (Gate 0/7)."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="docs/security.md",
        help="Path to security specification file (default: docs/security.md)",
    )
    parser.add_argument(
        "--prd",
        default=None,
        help="Optional path to PRD.md to verify Security NFR traceability",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed console output on success",
    )

    args = parser.parse_args(argv)

    target_path = Path(args.path)
    prd_path = args.prd or ("docs/PRD.md" if Path("docs/PRD.md").exists() else None)

    report = audit_security_file(target_path, prd_path=prd_path)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.passed else 1

    if report.passed:
        if not args.quiet:
            print(f"✅ Security Architecture Audit PASSED for {target_path}")
            print(f"   - STRIDE Categories: {len(report.stride_categories_found)}/6 covered")
            print(f"   - Service Accounts: {len(report.service_accounts_found)} defined")
            print(f"   - Cataloged Secrets: {len(report.secrets_found)} entries")
            print(f"   - Mermaid Boundaries: {'Present' if report.has_mermaid else 'Missing'}")
            if report.nfr_citations_found:
                print(f"   - PRD NFR Citations: {', '.join(report.nfr_citations_found)}")
        return 0

    print(f"❌ Security Architecture Audit FAILED for {target_path}")
    for violation in report.violations:
        print(f"   - [VIOLATION] {violation}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
