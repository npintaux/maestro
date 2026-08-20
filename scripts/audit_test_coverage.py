"""Independent Test Coverage Auditor (Gate 8 mechanical enforcement).

Cross-references a subsystem's frozen specifications against the orthogonal test suites the
Independent Test Architect (`/test-architect`) is required to author, so the gate cannot be
passed with a single happy-path test:

* Every HTTP status code documented in `openapi.yaml` is asserted by the contract test suite.
* Every PRD User Story the subsystem claims (via `SPEC.md`) is referenced by the behavioral suite.
* Every User Story claimed in `SPEC.md` actually exists in `docs/PRD.md` (traceability).
* The black-box isolation invariant holds: test suites never import the subsystem's private
  `domain/` or `adapters/` packages.

This complements `scripts/validate_contract.py` (which proves the contract is well-formed) by
proving the contract is independently verified.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

# A response key such as "200"/"404"/"500"; "default" and non-numeric keys are ignored.
STATUS_CODE_KEY_PATTERN = re.compile(r"^\d{3}$")
# Any 3-digit token, used to harvest asserted codes from a line mentioning `status_code`.
THREE_DIGIT_PATTERN = re.compile(r"\b(\d{3})\b")
# PRD User Story identifier, e.g. "US-1" (matched case-insensitively, normalized to upper).
STORY_ID_PATTERN = re.compile(r"\bUS-\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class CoverageAuditReport:
    """Report cross-referencing frozen specs against the independent test suites."""

    is_valid: bool
    file_path: str
    subsystem: str
    documented_status_codes: list[str] = field(default_factory=list)
    covered_status_codes: list[str] = field(default_factory=list)
    claimed_story_ids: list[str] = field(default_factory=list)
    covered_story_ids: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def _documented_status_codes(openapi_text: str) -> tuple[set[str], list[str]]:
    """Collect every numeric response status code declared across all operations.

    Returns:
        A tuple of (status codes, parse violations).
    """
    if not openapi_text.strip():
        return set(), ["openapi.yaml is missing or empty; cannot audit status-code coverage."]

    try:
        spec = yaml.safe_load(openapi_text)
    except yaml.YAMLError as err:
        return set(), [f"Could not parse openapi.yaml for status-code coverage: {err}"]

    codes: set[str] = set()
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if isinstance(paths, dict):
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            for op_item in path_item.values():
                if not isinstance(op_item, dict):
                    continue
                responses = op_item.get("responses")
                if isinstance(responses, dict):
                    codes.update(
                        str(code) for code in responses if STATUS_CODE_KEY_PATTERN.match(str(code))
                    )
    return codes, []


def _asserted_status_codes(contract_test_text: str) -> set[str]:
    """Harvest 3-digit codes asserted on any line referencing `status_code`."""
    codes: set[str] = set()
    for line in contract_test_text.splitlines():
        if "status_code" in line:
            codes.update(THREE_DIGIT_PATTERN.findall(line))
    return codes


def _story_ids(text: str) -> set[str]:
    """Extract normalized (upper-case) User Story identifiers from arbitrary text."""
    return {match.upper() for match in STORY_ID_PATTERN.findall(text)}


def _forbidden_domain_imports(text: str, subsystem: str) -> list[str]:
    """Return import lines that reach into the subsystem's private domain/adapters packages."""
    if not subsystem:
        return []
    pattern = re.compile(rf"modules\.{re.escape(subsystem)}\.(?:domain|adapters)\b")
    return [line.strip() for line in text.splitlines() if "import" in line and pattern.search(line)]


def audit_test_coverage(
    *,
    openapi_text: str,
    spec_text: str,
    contract_test_text: str,
    behavioral_test_text: str,
    prd_text: str,
    subsystem: str = "",
    file_path: str = "",
    contract_path: str = "contract test suite",
    behavioral_path: str = "behavioral test suite",
) -> CoverageAuditReport:
    """Audit the independent test suites against the frozen specs (pure core).

    Args:
        openapi_text: Raw text of the subsystem openapi.yaml.
        spec_text: Raw text of the subsystem SPEC.md (declares the claimed User Stories).
        contract_test_text: Raw text of the contract test suite.
        behavioral_test_text: Raw text of the behavioral test suite.
        prd_text: Raw text of docs/PRD.md (the universe of User Stories).
        subsystem: Subsystem identifier, used for isolation checks and messages.
        file_path: Source openapi path for reporting.
        contract_path: Contract test path for reporting.
        behavioral_path: Behavioral test path for reporting.

    Returns:
        CoverageAuditReport.
    """
    violations: list[str] = []

    documented, parse_violations = _documented_status_codes(openapi_text)
    violations.extend(parse_violations)

    if not contract_test_text.strip():
        violations.append(f"Contract test suite is missing or empty at '{contract_path}'.")
    if not behavioral_test_text.strip():
        violations.append(f"Behavioral test suite is missing or empty at '{behavioral_path}'.")

    asserted = _asserted_status_codes(contract_test_text)
    covered_codes = documented & asserted
    for code in sorted(documented - asserted):
        violations.append(
            f"openapi.yaml documents status code '{code}' but no contract test asserts it."
        )

    prd_ids = _story_ids(prd_text)
    claimed_ids = _story_ids(spec_text)
    referenced_ids = _story_ids(behavioral_test_text)
    covered_ids = claimed_ids & referenced_ids

    for story in sorted(claimed_ids - prd_ids):
        violations.append(
            f"SPEC.md claims '{story}' but that User Story is not defined in docs/PRD.md."
        )
    for story in sorted(claimed_ids - referenced_ids):
        violations.append(
            f"SPEC.md claims '{story}' but no behavioral test references it (missing traceability)."
        )
    if not claimed_ids:
        violations.append(
            "SPEC.md declares no PRD User Stories (US-N); cannot verify behavioral coverage."
        )

    for offending in _forbidden_domain_imports(contract_test_text, subsystem):
        violations.append(
            f"Contract test breaks black-box isolation by importing private code: '{offending}'."
        )
    for offending in _forbidden_domain_imports(behavioral_test_text, subsystem):
        violations.append(
            f"Behavioral test breaks black-box isolation by importing private code: '{offending}'."
        )

    return CoverageAuditReport(
        is_valid=not violations,
        file_path=file_path,
        subsystem=subsystem,
        documented_status_codes=sorted(documented),
        covered_status_codes=sorted(covered_codes),
        claimed_story_ids=sorted(claimed_ids),
        covered_story_ids=sorted(covered_ids),
        violations=violations,
    )


def _safe_read(path: Path) -> str:
    """Read a file's text, returning '' when it is absent."""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover
        return ""


def audit_subsystem_tests(
    openapi_path: str | Path,
    *,
    prd_path: str | Path | None = None,
) -> CoverageAuditReport:
    """Audit test coverage for the subsystem owning ``openapi_path``.

    The subsystem name is the parent directory of ``openapi.yaml``, and the repository root is
    inferred from the canonical ``<root>/src/modules/<subsystem>/openapi.yaml`` layout. Test and
    PRD locations follow the Test Architect's conventional directory structure.

    Args:
        openapi_path: Path to the subsystem's openapi.yaml.
        prd_path: Optional override for the PRD location (defaults to ``<root>/docs/PRD.md``).

    Returns:
        CoverageAuditReport.
    """
    path = Path(openapi_path)
    subsystem = path.parent.name
    root = path.resolve().parents[3]

    spec_file = path.parent / "SPEC.md"
    contract_file = root / "tests" / "contract" / subsystem / f"test_contract_{subsystem}.py"
    behavioral_file = root / "tests" / "behavioral" / subsystem / f"test_behavioral_{subsystem}.py"
    prd_file = Path(prd_path) if prd_path is not None else root / "docs" / "PRD.md"

    return audit_test_coverage(
        openapi_text=_safe_read(path),
        spec_text=_safe_read(spec_file),
        contract_test_text=_safe_read(contract_file),
        behavioral_test_text=_safe_read(behavioral_file),
        prd_text=_safe_read(prd_file),
        subsystem=subsystem,
        file_path=str(path),
        contract_path=str(contract_file),
        behavioral_path=str(behavioral_file),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for Gate 8 independent-test-coverage auditing."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit that a subsystem's orthogonal contract and behavioral test suites cover every "
            "documented status code and claimed PRD User Story."
        )
    )
    parser.add_argument(
        "file",
        help="Path to the subsystem OpenAPI spec (e.g., src/modules/shortener_api/openapi.yaml).",
    )
    parser.add_argument(
        "--prd",
        default=None,
        help="Override path to docs/PRD.md (defaults to the inferred repository root).",
    )

    args = parser.parse_args(argv)

    report = audit_subsystem_tests(args.file, prd_path=args.prd)
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: Test coverage audit failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
