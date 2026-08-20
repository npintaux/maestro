"""Google Cloud Well-Architected Framework (WAF) Compliance Auditor.

Mechanically audits architecture specifications (architecture.md) against the 7 Google Cloud
Well-Architected Framework pillars. The audit is deliberately hard to game:

* Every pillar must be addressed in its **own heading section** that carries an official
  ``cloud.google.com/architecture/framework/...`` citation (a summary list that merely names
  the pillars does not pass).
* The architect must **freeze concrete cloud service choices** in a dedicated
  "Frozen Cloud Service Decisions" table with a *Chosen GCP Service* column and a
  *WAF-driver rationale* column. Service selection is read from that authoritative table, not
  from incidental prose mentions.
* Subsystem module boundaries (``src/modules/<subsystem>/``) must be declared.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

MIN_FROZEN_SERVICES = 3

# 7 Canonical Pillars and matching regex patterns (matched against section headings).
PILLAR_PATTERNS: dict[str, re.Pattern[str]] = {
    "system_design": re.compile(r"\b(system\s+design|system-design)\b", re.IGNORECASE),
    "operational_excellence": re.compile(
        r"\b(operational\s+excellence|operational-excellence)\b", re.IGNORECASE
    ),
    "security": re.compile(
        r"\b(security(\s*,?\s*privacy(\s*,?\s*and\s*compliance)?)?|security-privacy-compliance)\b",
        re.IGNORECASE,
    ),
    "reliability": re.compile(
        r"\b(reliability(\s*,?\s*and\s*disaster\s*recovery)?|reliability-dr)\b", re.IGNORECASE
    ),
    "cost_optimization": re.compile(r"\b(cost\s+optimization|cost-optimization)\b", re.IGNORECASE),
    "performance": re.compile(
        r"\b(performance(\s+optimization)?|performance-optimization)\b", re.IGNORECASE
    ),
    "sustainability": re.compile(r"\b(sustainability)\b", re.IGNORECASE),
}

# Recognized GCP Services
GCP_SERVICES: list[str] = [
    "Cloud Run",
    "GKE",
    "Google Kubernetes Engine",
    "Cloud Functions",
    "Compute Engine",
    "Cloud SQL",
    "Spanner",
    "Cloud Spanner",
    "AlloyDB",
    "Firestore",
    "BigQuery",
    "Bigtable",
    "Cloud Storage",
    "Pub/Sub",
    "Eventarc",
    "Cloud Tasks",
    "Cloud Armor",
    "Secret Manager",
    "Cloud KMS",
    "Cloud Logging",
    "Cloud Monitoring",
    "Cloud Trace",
    "Cloud Deploy",
    "Cloud Build",
    "Artifact Registry",
    "Memorystore",
    "Cloud CDN",
    "Cloud Load Balancing",
    "Identity-Aware Proxy",
    "IAP",
    "Workload Identity",
    "Cloud IAM",
]

DOCS_URL_PATTERN = re.compile(
    r"https?://(docs\.)?cloud\.google\.com/architecture/framework/|https?://github\.com/google/skills",
    re.IGNORECASE,
)

SUBSYSTEM_PATH_PATTERN = re.compile(
    r"src/modules/([a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)

# Heading of the mandatory frozen decision record (e.g. "## Frozen Cloud Service Decisions").
FROZEN_HEADING_PATTERN = re.compile(r"frozen.*\bdecision", re.IGNORECASE)

# Markdown heading line (levels 1-6).
HEADING_PATTERN = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)

# Column-header keywords identifying the rationale/WAF-driver column of the frozen table.
RATIONALE_HEADER_KEYWORDS = ("rationale", "driver", "justification", "waf")

# Phrases that mark a service mention as an explicit *exclusion* rather than a selection.
EXCLUSION_PATTERN = re.compile(
    r"\b(exclud\w*|avoid\w*|instead\s+of|rather\s+than|reject\w*|eliminat\w*|not\s+use\w*|no\s+longer)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WafAuditReport:
    """Comprehensive report of WAF compliance audit."""

    is_valid: bool
    file_path: str
    pillars_found: list[str] = field(default_factory=list)
    pillars_missing: list[str] = field(default_factory=list)
    pillars_uncited: list[str] = field(default_factory=list)
    frozen_services: list[str] = field(default_factory=list)
    docs_citations_count: int = 0
    gcp_services_mentioned: list[str] = field(default_factory=list)
    subsystems_found: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def _split_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown into (heading_text, section_body) pairs.

    Each section body spans from its heading up to (but excluding) the next heading. Content
    before the first heading is ignored, since pillars and frozen decisions live under headings.

    Args:
        content: Raw markdown text.

    Returns:
        Ordered list of (heading_text, body_including_heading) tuples.
    """
    matches = list(HEADING_PATTERN.finditer(content))
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        heading = match.group().lstrip("#").strip()
        sections.append((heading, content[start:end]))
    return sections


def _match_service(cell: str) -> str | None:
    """Return the canonical GCP service named in ``cell``, or None if unrecognized."""
    for svc in GCP_SERVICES:
        if re.search(rf"\b{re.escape(svc)}\b", cell, re.IGNORECASE):
            return svc
    return None


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into stripped cell values."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(cells: Sequence[str]) -> bool:
    """Return True if the cells form a markdown table separator (e.g. ``---``)."""
    non_empty = [c for c in cells if c]
    return bool(non_empty) and all(re.fullmatch(r":?-{3,}:?", c) for c in non_empty)


def _parse_frozen_decisions(body: str) -> tuple[list[str], list[str]]:
    """Parse the frozen-decisions table, returning (chosen_services, issues).

    Args:
        body: Markdown body of the "Frozen Cloud Service Decisions" section.

    Returns:
        A tuple of the recognized chosen GCP services and any structural/validation issues.
    """
    issues: list[str] = []
    table_lines = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(table_lines) < 3:
        issues.append(
            "Frozen Cloud Service Decisions section must contain a markdown table with a header "
            "and at least one decision row."
        )
        return [], issues

    header = _split_row(table_lines[0])
    service_idx = next((i for i, h in enumerate(header) if "service" in h.lower()), None)
    rationale_idx = next(
        (i for i, h in enumerate(header) if any(k in h.lower() for k in RATIONALE_HEADER_KEYWORDS)),
        None,
    )

    if service_idx is None:
        issues.append(
            "Frozen decisions table must include a column header containing 'Service' "
            "(the Chosen GCP Service)."
        )
    if rationale_idx is None:
        issues.append(
            "Frozen decisions table must include a rationale/WAF-driver column justifying "
            "each service choice."
        )
    if service_idx is None:
        return [], issues

    services: list[str] = []
    for line in table_lines[1:]:
        cells = _split_row(line)
        if _is_separator_row(cells):
            continue
        if service_idx >= len(cells) or not cells[service_idx]:
            continue
        cell = cells[service_idx]
        svc = _match_service(cell)
        if svc is None:
            issues.append(
                f"Frozen decision lists an unrecognized/ambiguous GCP service: '{cell}'. "
                "Name a concrete GCP product."
            )
            continue
        if rationale_idx is not None and (rationale_idx >= len(cells) or not cells[rationale_idx]):
            issues.append(f"Frozen decision for '{svc}' is missing a rationale/WAF driver.")
        services.append(svc)

    return sorted(set(services)), issues


def _mentioned_services(content: str) -> list[str]:
    """Return GCP services mentioned as selections (ignoring exclusion-only mentions)."""
    lines = content.splitlines()
    found: list[str] = []
    for svc in GCP_SERVICES:
        pattern = re.compile(rf"\b{re.escape(svc)}\b", re.IGNORECASE)
        mentions = [ln for ln in lines if pattern.search(ln)]
        if mentions and any(not EXCLUSION_PATTERN.search(ln) for ln in mentions):
            found.append(svc)
    return found


def audit_architecture_text(content: str, file_path: str = "") -> WafAuditReport:
    """Audit markdown content for WAF compliance across the 7 pillars.

    Args:
        content: Raw markdown text of the architecture specification.
        file_path: Source file path for reporting.

    Returns:
        WafAuditReport with detailed compliance findings.
    """
    if not content or not content.strip():
        return WafAuditReport(
            is_valid=False,
            file_path=file_path,
            violations=["Document is empty or contains only whitespace."],
        )

    sections = _split_sections(content)
    violations: list[str] = []

    # 1. Each pillar must have its own heading section carrying a framework citation.
    found_pillars: list[str] = []
    missing_pillars: list[str] = []
    uncited_pillars: list[str] = []
    for pillar_name, pattern in PILLAR_PATTERNS.items():
        matching_bodies = [body for heading, body in sections if pattern.search(heading)]
        if not matching_bodies:
            missing_pillars.append(pillar_name)
            continue
        found_pillars.append(pillar_name)
        if not any(DOCS_URL_PATTERN.search(body) for body in matching_bodies):
            uncited_pillars.append(pillar_name)

    if missing_pillars:
        violations.append(
            f"Missing dedicated sections for GCP WAF pillars: {', '.join(missing_pillars)}."
        )
    if uncited_pillars:
        violations.append(
            "Pillars addressed without an official Google Cloud Architecture Framework "
            f"documentation citation in their section: {', '.join(uncited_pillars)}."
        )

    # 2. The architect must freeze concrete cloud service choices in an authoritative table.
    frozen_sections = [body for heading, body in sections if FROZEN_HEADING_PATTERN.search(heading)]
    frozen_services: list[str] = []
    if not frozen_sections:
        violations.append(
            "Missing a 'Frozen Cloud Service Decisions' section; the architect must freeze "
            "concrete GCP service choices with a per-choice WAF-driver rationale."
        )
    else:
        frozen_services, frozen_issues = _parse_frozen_decisions(frozen_sections[0])
        violations.extend(frozen_issues)
        if len(frozen_services) < MIN_FROZEN_SERVICES:
            violations.append(
                "Frozen Cloud Service Decisions must commit to at least "
                f"{MIN_FROZEN_SERVICES} concrete GCP services (found {len(frozen_services)})."
            )

    # 3. Subsystem module boundaries must be declared.
    subsystems_found = sorted(set(SUBSYSTEM_PATH_PATTERN.findall(content)))
    if not subsystems_found:
        violations.append(
            "No subsystem module paths found (expected paths matching 'src/modules/<subsystem>/')."
        )

    # Informational metrics.
    citations_count = len(DOCS_URL_PATTERN.findall(content))
    services_mentioned = _mentioned_services(content)

    return WafAuditReport(
        is_valid=len(violations) == 0,
        file_path=file_path,
        pillars_found=found_pillars,
        pillars_missing=missing_pillars,
        pillars_uncited=uncited_pillars,
        frozen_services=frozen_services,
        docs_citations_count=citations_count,
        gcp_services_mentioned=services_mentioned,
        subsystems_found=subsystems_found,
        violations=violations,
    )


def audit_architecture_file(file_path: str | Path) -> WafAuditReport:
    """Read and audit an architecture markdown file on disk.

    Args:
        file_path: Path to the architecture.md file.

    Returns:
        WafAuditReport.
    """
    path = Path(file_path)
    if not path.is_file():
        return WafAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"File not found or not a valid file: '{path}'."],
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:  # pragma: no cover
        return WafAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"Failed to read file: {err}"],
        )

    return audit_architecture_text(content, str(path))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for WAF compliance audit."""
    parser = argparse.ArgumentParser(
        description="Audit architecture.md for Google Cloud Well-Architected Framework compliance."
    )
    parser.add_argument(
        "file",
        help="Path to the architecture markdown file to audit (e.g., architecture.md).",
    )

    args = parser.parse_args(argv)

    report = audit_architecture_file(args.file)
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: WAF Audit failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
