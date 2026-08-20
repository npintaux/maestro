"""Contract & Schema Validator for Subsystem OpenAPI 3.x Specifications.

Mechanically validates openapi.yaml specifications to ensure complete, ungameable contract
definitions before developers write code:
* Valid OpenAPI 3.x structure with info (title, version) and non-empty paths.
* Mandatory API path versioning (/v1/, /v2/, etc.).
* Explicit operationIds and summary/descriptions for all HTTP operations.
* Complete HTTP status code coverage (2xx success, 4xx client errors, and 500 server errors).
* Fully defined components.schemas with typed properties and verified $ref integrity.

It also gates the sibling SPEC.md so the Tech Lead cannot skip the domain-pattern decision:
* A single, recognized 'Selected Domain Pattern' is declared (one of the 5 Maestro patterns).
* No unresolved template placeholders remain for the pattern or its domain file layout.
* The SPEC.md references the concrete domain artifact(s) required by the chosen pattern.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
VERSIONED_PATH_PATTERN = re.compile(r"^/v[0-9]+(/.*)?$")
SCHEMA_REF_PATTERN = re.compile(r"^#/components/schemas/([a-zA-Z0-9_\-]+)$")

# --- SPEC.md domain-pattern gating -------------------------------------------------------------
# The five canonical Maestro domain patterns (see skills/lead-decompose/references/patterns/).
VALID_PATTERNS: tuple[str, ...] = (
    "decision-list",
    "repository-service",
    "state-machine",
    "pipeline-reducer",
    "algorithmic-core",
)

# Concrete domain artifact(s) the SPEC.md must reference once a pattern is chosen. These mirror
# the canonical port/coordinator file names in each references/patterns/<pattern>.md.
PATTERN_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "decision-list": ("rules/base.py", "engine.py"),
    "repository-service": ("repository.py", "service.py"),
    "state-machine": ("state_machine.py",),
    "pipeline-reducer": ("stages/base.py", "pipeline.py"),
    "algorithmic-core": ("solver.py",),
}

# Matches the mandatory blockquote header, capturing the backtick-quoted pattern value:
#   > **Selected Domain Pattern**: `state-machine`
SELECTED_PATTERN_PATTERN = re.compile(
    r"\*\*Selected Domain Pattern\*\*:\s*`([^`]+)`", re.IGNORECASE
)

# Matches an unresolved template file-layout placeholder such as
#   [rules/base.py | repository.py | state_machine.py | stages/base.py | solver.py]
# Requiring a literal ".py" avoids false positives on legitimate type hints like list[str | None].
FILE_PLACEHOLDER_PATTERN = re.compile(r"\[[^\]]*\.py[^\]]*\|[^\]]*\]")


@dataclass(frozen=True)
class ContractAuditReport:
    """Detailed audit report for OpenAPI contract validation."""

    is_valid: bool
    file_path: str
    endpoints_found: list[str] = field(default_factory=list)
    schemas_found: list[str] = field(default_factory=list)
    status_codes_checked: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    selected_pattern: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


@dataclass(frozen=True)
class SpecAuditReport:
    """Detailed audit report for a subsystem SPEC.md domain-pattern declaration."""

    is_valid: bool
    file_path: str
    selected_pattern: str | None = None
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def _collect_refs(node: Any) -> list[str]:
    """Recursively collect all $ref strings in a schema/response tree."""
    refs: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                refs.append(v)
            else:
                refs.extend(_collect_refs(v))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_refs(item))
    return refs


def audit_contract_text(content: str, file_path: str = "") -> ContractAuditReport:
    """Audit OpenAPI specification text against contract completeness rules.

    Args:
        content: Raw YAML text of the OpenAPI specification.
        file_path: Source file path for reporting.

    Returns:
        ContractAuditReport.
    """
    if not content or not content.strip():
        return ContractAuditReport(
            is_valid=False,
            file_path=file_path,
            violations=["OpenAPI contract specification is empty."],
        )

    try:
        spec = yaml.safe_load(content)
    except yaml.YAMLError as err:
        return ContractAuditReport(
            is_valid=False,
            file_path=file_path,
            violations=[f"Invalid YAML syntax: {err}"],
        )

    if not isinstance(spec, dict):
        return ContractAuditReport(
            is_valid=False,
            file_path=file_path,
            violations=["OpenAPI root document must be a mapping/dictionary."],
        )

    violations: list[str] = []
    endpoints_found: list[str] = []
    status_codes_checked: list[str] = []

    # 1. Check OpenAPI Version
    openapi_version = spec.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3."):
        violations.append(
            f"Missing or unsupported 'openapi: 3.x' version declaration (got {openapi_version!r})."
        )

    # 2. Check Info Block
    info = spec.get("info")
    if not isinstance(info, dict) or not info.get("title") or not info.get("version"):
        violations.append(
            "Missing or incomplete 'info' block (must include 'title' and 'version')."
        )

    # 3. Check Components Schemas
    components = spec.get("components")
    schemas: dict[str, Any] = {}
    if isinstance(components, dict) and isinstance(components.get("schemas"), dict):
        schemas = components["schemas"]
    else:
        violations.append(
            "Missing mandatory 'components.schemas' section defining domain data models."
        )

    schemas_found = sorted(schemas.keys())

    for schema_name, schema_def in schemas.items():
        if (
            isinstance(schema_def, dict)
            and schema_def.get("type") == "object"
            and not schema_def.get("properties")
        ):
            violations.append(
                f"Schema '{schema_name}' declares type: object but defines no properties."
            )

    # 4. Check Paths and Operations
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        violations.append("No endpoints defined under 'paths'.")
    else:
        for path_str, path_item in paths.items():
            if not isinstance(path_str, str) or not VERSIONED_PATH_PATTERN.match(path_str):
                violations.append(
                    f"Endpoint path '{path_str}' must start with a version prefix (e.g. '/v1/...')."
                )

            if not isinstance(path_item, dict):
                continue

            for method, op_item in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(op_item, dict):
                    continue

                endpoint_tag = f"{method.upper()} {path_str}"
                endpoints_found.append(endpoint_tag)

                op_id = op_item.get("operationId")
                if not op_id:
                    violations.append(f"Endpoint {endpoint_tag} is missing 'operationId' field.")

                responses = op_item.get("responses")
                if not isinstance(responses, dict) or not responses:
                    violations.append(f"Endpoint {endpoint_tag} must define response status codes.")
                    continue

                codes = [str(c) for c in responses]
                status_codes_checked.extend(codes)

                has_2xx = any(c.startswith("2") for c in codes)
                has_4xx = any(c.startswith("4") for c in codes)
                has_5xx = any(c.startswith("5") or c == "default" for c in codes)

                if not has_2xx:
                    violations.append(f"Endpoint {endpoint_tag} lacks a 2xx success response.")
                if not has_4xx:
                    violations.append(
                        f"Endpoint {endpoint_tag} lacks a 4xx error response (e.g. 400 or 422)."
                    )
                if not has_5xx:
                    violations.append(f"Endpoint {endpoint_tag} lacks a 500 server error response.")

    # 5. Check $ref Integrity
    all_refs = _collect_refs(spec)
    for ref in all_refs:
        match = SCHEMA_REF_PATTERN.match(ref)
        if match:
            target_schema = match.group(1)
            if target_schema not in schemas:
                violations.append(
                    f"Unresolved schema reference: '{ref}' not found in components.schemas."
                )

    is_valid = len(violations) == 0

    return ContractAuditReport(
        is_valid=is_valid,
        file_path=file_path,
        endpoints_found=sorted(set(endpoints_found)),
        schemas_found=schemas_found,
        status_codes_checked=sorted(set(status_codes_checked)),
        violations=violations,
    )


def audit_contract_file(file_path: str | Path) -> ContractAuditReport:
    """Read and audit an OpenAPI contract YAML file on disk.

    Args:
        file_path: Path to openapi.yaml.

    Returns:
        ContractAuditReport.
    """
    path = Path(file_path)
    if not path.is_file():
        return ContractAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"File not found or not a valid file: '{path}'."],
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:  # pragma: no cover
        return ContractAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"Failed to read file: {err}"],
        )

    return audit_contract_text(content, str(path))


def audit_spec_text(content: str, file_path: str = "") -> SpecAuditReport:
    """Audit SPEC.md text for a single, resolved, recognized domain-pattern declaration.

    Args:
        content: Raw Markdown text of the subsystem SPEC.md.
        file_path: Source file path for reporting.

    Returns:
        SpecAuditReport.
    """
    if not content or not content.strip():
        return SpecAuditReport(
            is_valid=False,
            file_path=file_path,
            violations=["Subsystem SPEC.md is empty."],
        )

    violations: list[str] = []
    selected_pattern: str | None = None

    match = SELECTED_PATTERN_PATTERN.search(content)
    if match is None:
        violations.append(
            "SPEC.md is missing the '> **Selected Domain Pattern**: `<pattern>`' declaration."
        )
    else:
        raw = match.group(1).strip()
        if any(ch in raw for ch in "[]|"):
            violations.append(
                f"Selected Domain Pattern is an unresolved template placeholder ({raw!r}); "
                f"pick exactly one of: {', '.join(VALID_PATTERNS)}."
            )
        elif raw.lower() not in VALID_PATTERNS:
            violations.append(
                f"Selected Domain Pattern '{raw}' is not a recognized Maestro pattern; "
                f"must be one of: {', '.join(VALID_PATTERNS)}."
            )
        else:
            selected_pattern = raw.lower()

    if FILE_PLACEHOLDER_PATTERN.search(content):
        violations.append(
            "SPEC.md still contains an unresolved '[fileA.py | fileB.py | ...]' layout "
            "placeholder; resolve it to the concrete domain file(s) for the selected pattern."
        )

    if selected_pattern is not None:
        # Ignore any leftover placeholder text so its options cannot satisfy the artifact check.
        resolved = FILE_PLACEHOLDER_PATTERN.sub("", content)
        for artifact in PATTERN_ARTIFACTS[selected_pattern]:
            if artifact not in resolved:
                violations.append(
                    f"SPEC.md declares the '{selected_pattern}' pattern but never references its "
                    f"required domain artifact '{artifact}'."
                )

    return SpecAuditReport(
        is_valid=not violations,
        file_path=file_path,
        selected_pattern=selected_pattern,
        violations=violations,
    )


def audit_spec_file(file_path: str | Path) -> SpecAuditReport:
    """Read and audit a subsystem SPEC.md file on disk.

    Args:
        file_path: Path to SPEC.md.

    Returns:
        SpecAuditReport.
    """
    path = Path(file_path)
    if not path.is_file():
        return SpecAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"Subsystem SPEC.md not found at '{path}' (required for Gate 1)."],
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:  # pragma: no cover
        return SpecAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"Failed to read SPEC.md: {err}"],
        )

    return audit_spec_text(content, str(path))


def audit_subsystem(openapi_path: str | Path) -> ContractAuditReport:
    """Audit an openapi.yaml and its sibling SPEC.md as one combined Gate 1 report.

    Args:
        openapi_path: Path to the subsystem's openapi.yaml.

    Returns:
        A ContractAuditReport merging contract and SPEC.md violations. The report is valid only
        when both the OpenAPI contract and the SPEC.md domain-pattern declaration pass.
    """
    contract = audit_contract_file(openapi_path)
    spec = audit_spec_file(Path(openapi_path).parent / "SPEC.md")
    violations = [*contract.violations, *spec.violations]

    return ContractAuditReport(
        is_valid=not violations,
        file_path=contract.file_path,
        endpoints_found=contract.endpoints_found,
        schemas_found=contract.schemas_found,
        status_codes_checked=contract.status_codes_checked,
        violations=violations,
        selected_pattern=spec.selected_pattern,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for combined Gate 1 contract + SPEC.md validation."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit a subsystem's openapi.yaml (and sibling SPEC.md) for strict contract "
            "completeness, schema validity, and a resolved domain-pattern declaration."
        )
    )
    parser.add_argument(
        "file",
        help="Path to the OpenAPI specification file (e.g., src/modules/billing/openapi.yaml).",
    )

    args = parser.parse_args(argv)

    report = audit_subsystem(args.file)
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: Contract validation failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
