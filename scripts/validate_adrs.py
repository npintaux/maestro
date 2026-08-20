"""Architecture Decision Record (ADR) and Human-in-the-Loop Approval Validator.

Mechanically enforces MADR (Markdown Architecture Decision Record) compliance,
monotonic sequential numbering, required analytical sections, superseded status linkage,
traceability to frozen architecture decisions, and Gate 0.5 Human Approval tokens.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

REQUIRED_MADR_SECTIONS: list[tuple[str, str]] = [
    ("Context and Problem Statement", r"##\s+(?:Context\s+and\s+Problem\s+Statement|Context)"),
    ("Decision Drivers", r"##\s+Decision\s+Drivers"),
    ("Considered Options", r"##\s+Considered\s+Options"),
    ("Decision Outcome", r"##\s+Decision\s+Outcome"),
    ("Consequences", r"###?\s+(?:Positive\s+Consequences|Consequences|Negative\s+Consequences)"),
    (
        "Pros and Cons of the Options",
        r"##\s+(?:Pros\s+and\s+Cons\s+of\s+the\s+Options|Pros\s+and\s+Cons)",
    ),
]

VALID_STATUSES = {"proposed", "accepted", "superseded", "deprecated", "rejected"}


@dataclass(frozen=True)
class AdrValidationResult:
    """Validation result for an individual ADR document."""

    is_valid: bool
    filename: str
    adr_id: str | None = None
    title: str | None = None
    status: str | None = None
    superseded_by: str | None = None
    approved_by: str | None = None
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert result to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


@dataclass(frozen=True)
class AdrDirectoryReport:
    """Aggregate validation report for an ADR directory."""

    is_valid: bool
    adr_count: int
    results: list[AdrValidationResult]
    directory_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert aggregate report to serializable dictionary."""
        return {
            "valid": self.is_valid,
            "adr_count": self.adr_count,
            "directory_violations": list(self.directory_violations),
            "results": [r.to_dict() for r in self.results],
        }


def _is_placeholder_value(val: str | None) -> bool:
    """Check if a string is None, empty, or a template placeholder."""
    if not val or not val.strip():
        return True
    s = val.strip().lower()
    if s in {"n/a", "none", "tbd", "todo", "{...}", "unknown"}:
        return True
    return bool(s.startswith("{") and s.endswith("}"))


def validate_adr_content(
    content: str,
    filename: str = "<memory>",
    require_approval: bool = False,
) -> AdrValidationResult:
    """Validate a single ADR's Markdown content against MADR standards.

    Args:
        content: Raw markdown string of the ADR.
        filename: Name or path of the ADR file.
        require_approval: If True (Gate 0.5), requires non-placeholder 'Approved-by'.

    Returns:
        AdrValidationResult detailing validity and identified violations.
    """
    violations: list[str] = []

    if not content or not content.strip():
        return AdrValidationResult(
            is_valid=False,
            filename=filename,
            violations=["ADR document is empty."],
        )

    # 1. Title check: # [ADR-XXXX] Title or # ADR-XXXX: Title
    title_match = re.search(
        r"^#\s+\[?(?:ADR-)?(\d{4})\]?[:\s]+(.+)$", content, re.MULTILINE | re.IGNORECASE
    )
    adr_id: str | None = None
    title: str | None = None
    if title_match:
        adr_id = title_match.group(1)
        title = title_match.group(2).strip()
    else:
        violations.append(
            "Missing or invalid ADR title heading. "
            "Expected format: '# [ADR-0001] Title' or '# ADR-0001: Title'."
        )

    # 2. Metadata Status check
    status_match = re.search(
        r"^\s*[\*\-]?\s*\*\*Status\*\*[:\s]+([a-zA-Z_\-]+)",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    status: str | None = None
    if status_match:
        raw_status = status_match.group(1).strip().lower()
        if raw_status in VALID_STATUSES:
            status = raw_status
        else:
            valid_list = ", ".join(sorted(VALID_STATUSES))
            violations.append(f"Invalid ADR Status '{raw_status}'. Must be one of: {valid_list}.")
    else:
        violations.append("Missing mandatory metadata field: '* **Status**: <status>'.")

    # 3. Superseded by check
    superseded_by: str | None = None
    superseded_match = re.search(
        r"^\s*[\*\-]?\s*\*\*Superseded\s+by\*\*[:\s]+(.+)$",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if superseded_match:
        raw_superseded = superseded_match.group(1).strip()
        if not _is_placeholder_value(raw_superseded):
            # Extract target ADR id if formatted as ADR-XXXX or XXXX
            target_match = re.search(r"(?:ADR-)?(\d{4})", raw_superseded, re.IGNORECASE)
            superseded_by = target_match.group(1) if target_match else raw_superseded

    if status == "superseded" and (not superseded_by or _is_placeholder_value(superseded_by)):
        violations.append(
            "ADR is marked as 'superseded' but lacks a valid target "
            "reference in '**Superseded by**'."
        )

    # 4. Approved-by check (Gate 0.5)
    approved_by: str | None = None
    approved_match = re.search(
        r"^\s*[\*\-]?\s*\*\*Approved-by\*\*[:\s]+(.+)$",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if approved_match:
        raw_approved = approved_match.group(1).strip()
        if not _is_placeholder_value(raw_approved):
            approved_by = raw_approved

    if (
        require_approval
        and status == "accepted"
        and (not approved_by or _is_placeholder_value(approved_by))
    ):
        violations.append(
            "Gate 0.5 sign-off failure: Accepted ADR lacks a verified "
            "'Approved-by:' reviewer token."
        )

    # 5. Required MADR Sections check
    for section_name, section_regex in REQUIRED_MADR_SECTIONS:
        if not re.search(section_regex, content, re.IGNORECASE | re.MULTILINE):
            violations.append(f"Missing mandatory MADR section: '{section_name}'.")

    is_valid = len(violations) == 0
    return AdrValidationResult(
        is_valid=is_valid,
        filename=filename,
        adr_id=adr_id,
        title=title,
        status=status,
        superseded_by=superseded_by,
        approved_by=approved_by,
        violations=violations,
    )


def validate_adr_file(
    file_path: str | Path,
    require_approval: bool = False,
) -> AdrValidationResult:
    """Read and validate a single ADR markdown file.

    Args:
        file_path: Path to the markdown file.
        require_approval: Whether to require Approved-by token.

    Returns:
        AdrValidationResult object.
    """
    path = Path(file_path)
    if not path.exists():
        return AdrValidationResult(
            is_valid=False,
            filename=str(file_path),
            violations=[f"ADR file '{file_path}' does not exist."],
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:
        return AdrValidationResult(
            is_valid=False,
            filename=str(file_path),
            violations=[f"Unable to read ADR file '{file_path}': {err}"],
        )

    return validate_adr_content(content, filename=path.name, require_approval=require_approval)


def _extract_frozen_decisions(arch_content: str) -> list[str]:
    """Extract services or ADR references from the Frozen Decisions table."""
    # Look for Frozen Cloud Service Decisions section
    section_match = re.search(
        r"##\s+.*?Frozen Cloud Service Decisions.*?\n([\s\S]*?)(?=\n##|\Z)",
        arch_content,
        re.IGNORECASE,
    )
    if not section_match:
        return []

    lines = section_match.group(1).splitlines()
    services: list[str] = []
    for line in lines:
        line_clean = line.strip()
        if not line_clean.startswith("|") or "---" in line_clean:
            continue
        cols = [c.strip() for c in line_clean.split("|")[1:-1]]
        if len(cols) >= 2 and cols[0].lower() not in {
            "architectural concern",
            "service / component",
            "service",
        }:
            service_name = cols[1] if len(cols) > 1 and cols[1] else cols[0]
            if service_name and not _is_placeholder_value(service_name):
                services.append(service_name)
    return services


def validate_adr_directory(
    adr_dir: str | Path,
    require_approval: bool = False,
    architecture_file: str | Path | None = None,
) -> AdrDirectoryReport:
    """Validate all ADR files in a directory for MADR compliance and consistency.

    Args:
        adr_dir: Path to directory containing ADR markdown files.
        require_approval: Whether Gate 0.5 sign-off is required.
        architecture_file: Optional path to architecture.md for cross-traceability.

    Returns:
        AdrDirectoryReport aggregate result.
    """
    dir_path = Path(adr_dir)
    dir_violations: list[str] = []

    if not dir_path.exists() or not dir_path.is_dir():
        return AdrDirectoryReport(
            is_valid=False,
            adr_count=0,
            results=[],
            directory_violations=[
                f"ADR directory '{adr_dir}' does not exist or is not a directory."
            ],
        )

    md_files = sorted([f for f in dir_path.iterdir() if f.is_file() and f.suffix == ".md"])
    if not md_files:
        return AdrDirectoryReport(
            is_valid=False,
            adr_count=0,
            results=[],
            directory_violations=[f"ADR directory '{adr_dir}' contains no markdown (.md) files."],
        )

    results: list[AdrValidationResult] = []
    adr_id_map: dict[str, AdrValidationResult] = {}
    extracted_ids: list[int] = []

    for file_path in md_files:
        res = validate_adr_file(file_path, require_approval=require_approval)
        results.append(res)
        if res.adr_id:
            extracted_ids.append(int(res.adr_id))
            adr_id_map[res.adr_id] = res

    # 1. Monotonic sequence check
    if extracted_ids:
        sorted_ids = sorted(extracted_ids)
        if sorted_ids[0] != 1:
            dir_violations.append(
                f"ADR sequence numbering must start at 0001 (found start: {sorted_ids[0]:04d})."
            )
        expected_range = list(range(1, len(sorted_ids) + 1))
        if sorted_ids != expected_range:
            dir_violations.append(
                f"ADR sequence numbering is non-contiguous or contains gaps: {sorted_ids}."
            )

    # 2. Superseded reference validity
    for res in results:
        if res.status == "superseded" and res.superseded_by and res.superseded_by not in adr_id_map:
            dir_violations.append(
                f"ADR '{res.filename}' is superseded by 'ADR-{res.superseded_by}', "
                f"which was not found in '{adr_dir}'."
            )

    # 3. Optional cross-check against architecture.md
    if architecture_file:
        arch_path = Path(architecture_file)
        if arch_path.exists():
            arch_content = arch_path.read_text(encoding="utf-8")
            frozen_services = _extract_frozen_decisions(arch_content)
            if frozen_services:
                # Ensure at least one accepted ADR exists covering architecture choices
                accepted_adrs = [r for r in results if r.status == "accepted"]
                if not accepted_adrs:
                    dir_violations.append(
                        "Architecture has frozen decisions, but no ADR has 'Status: accepted'."
                    )
        else:
            dir_violations.append(
                f"Referenced architecture file '{architecture_file}' does not exist."
            )

    all_valid = all(r.is_valid for r in results) and len(dir_violations) == 0

    return AdrDirectoryReport(
        is_valid=all_valid,
        adr_count=len(results),
        results=results,
        directory_violations=dir_violations,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ADR validation."""
    parser = argparse.ArgumentParser(
        description="Validate ADRs against MADR standards and Gate 0.5 sign-offs."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="docs/adr",
        help="Path to ADR directory (e.g. docs/adr) or single ADR markdown file.",
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Explicit path to single ADR markdown file.",
    )
    parser.add_argument(
        "--require-approval",
        "-a",
        action="store_true",
        help="Enforce Gate 0.5 sign-off (requires non-empty Approved-by on accepted ADRs).",
    )
    parser.add_argument(
        "--architecture",
        help="Optional path to architecture.md to cross-verify frozen decisions.",
    )

    args = parser.parse_args(argv)
    target_path = Path(args.file or args.target)

    if target_path.is_file():
        res = validate_adr_file(target_path, require_approval=args.require_approval)
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.is_valid else 1

    report = validate_adr_directory(
        target_path,
        require_approval=args.require_approval,
        architecture_file=args.architecture,
    )
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.is_valid else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
