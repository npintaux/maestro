"""Story <-> subsystem traceability coverage gate.

The product axis (PRD User Stories) and the technical axis (architecture subsystems) are
orthogonal and many-to-many: a story touches several subsystems, and a subsystem serves several
stories. Neither can be generated from the other, so the architect authors an explicit bridge,
``docs/traceability.md`` — a table mapping every ``US-N`` to the subsystem(s) that realize it.

This script is the gate that makes that bridge bite. Run at the Gate 0.5 -> Phase 2 handoff
(before subsystem issues and branches are created), it exits non-zero when the matrix leaves:
  * an **orphaned story**   — a PRD User Story with no subsystem mapping (value nobody builds);
  * a **speculative subsystem** — an architecture subsystem that serves no story (built for no one);
  * a **dangling reference** — the matrix cites a story not in the PRD, or a subsystem not in arch.

Ground truth is cross-referenced, not self-reported:
  * PRD User Stories are extracted from ``docs/PRD.md`` (``US-N``), matching the sibling
    audit_test_coverage convention so the two audits agree on the story set.
  * Subsystems are extracted from ``docs/architecture.md`` (``src/modules/<name>/``), matching
    the audit_waf_compliance convention.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

# PRD User Story identifier, e.g. "US-1" (case-insensitive, normalized to upper) — identical to
# scripts.audit_test_coverage so both audits share one definition of "the set of PRD stories".
STORY_ID_PATTERN = re.compile(r"\bUS-\d+\b", re.IGNORECASE)

# Subsystem module boundary declaration, e.g. "src/modules/redirect_resolver/" — identical to
# scripts.audit_waf_compliance so the subsystem set is defined one way across the plugin.
SUBSYSTEM_PATH_PATTERN = re.compile(r"src/modules/([a-zA-Z0-9_\-]+)")

# A subsystem token in a matrix cell (after the src/modules/ prefix is stripped).
_SUBSYSTEM_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-]*")

# Placeholder cell contents that mean "not mapped yet" — treated as an empty mapping (orphaned),
# never as a subsystem name.
_PLACEHOLDERS = frozenset({"tbd", "none", "n/a", "na", "todo", "-", "—"})


def _story_ids(text: str) -> set[str]:
    """Extract normalized PRD User Story identifiers (US-N) from text."""
    return {m.upper() for m in STORY_ID_PATTERN.findall(text)}


def _subsystem_names(text: str) -> set[str]:
    """Extract declared subsystem names (src/modules/<name>) from text."""
    return set(SUBSYSTEM_PATH_PATTERN.findall(text))


def _parse_subsystem_cell(cell: str) -> set[str]:
    """Extract subsystem names from a matrix cell, tolerating ``src/modules/`` prefixes,
    backticks, and comma/space separation. Placeholder tokens map to the empty set."""
    normalized = cell.replace("src/modules/", " ")
    tokens = set(_SUBSYSTEM_TOKEN_PATTERN.findall(normalized))
    return {t for t in tokens if t.lower() not in _PLACEHOLDERS}


def _parse_matrix(text: str) -> dict[str, set[str]]:
    """Parse ``docs/traceability.md`` markdown table rows into ``{US-N: {subsystems}}``.

    A row contributes only if it names at least one ``US-N`` in its first cell; header and
    separator rows carry none and are naturally ignored. Subsystems accumulate across rows.
    """
    mapping: dict[str, set[str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        stories = {m.upper() for m in STORY_ID_PATTERN.findall(cells[0])}
        if not stories:
            continue
        subs = _parse_subsystem_cell(cells[1]) if len(cells) > 1 else set()
        for story in stories:
            mapping.setdefault(story, set()).update(subs)
    return mapping


@dataclass
class TraceabilityReport:
    """Result of the story <-> subsystem traceability audit."""

    prd_stories: list[str] = field(default_factory=list)
    architecture_subsystems: list[str] = field(default_factory=list)
    matrix_stories: list[str] = field(default_factory=list)
    matrix_subsystems: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.is_valid, **asdict(self)}


def audit_traceability(
    prd_text: str, architecture_text: str, traceability_text: str
) -> TraceabilityReport:
    """Audit the traceability matrix against the PRD and architecture ground truth."""
    prd_stories = _story_ids(prd_text)
    arch_subs = _subsystem_names(architecture_text)
    mapping = _parse_matrix(traceability_text)
    matrix_stories = set(mapping)
    matrix_subs = {s for subs in mapping.values() for s in subs}

    violations: list[str] = []

    if not prd_stories:
        violations.append("docs/PRD.md declares no User Stories (US-N); nothing to trace.")
    if not arch_subs:
        violations.append(
            "docs/architecture.md declares no subsystems (src/modules/<name>/); nothing to trace."
        )
    if not mapping:
        violations.append(
            "docs/traceability.md contains no story->subsystem rows "
            "(expected a markdown table mapping each US-N to its subsystem(s))."
        )

    # Orphaned stories: a PRD story with no (real) subsystem mapping.
    for story in sorted(prd_stories):
        if not mapping.get(story):
            violations.append(
                f"orphaned story: {story} is in docs/PRD.md but maps to no subsystem in the matrix."
            )

    # Speculative subsystems: an architecture subsystem no story relies on.
    for sub in sorted(arch_subs):
        if sub not in matrix_subs:
            violations.append(
                f"speculative subsystem: '{sub}' is in docs/architecture.md but serves no story."
            )

    # Dangling references: the matrix cites things that do not exist in the ground truth.
    for story in sorted(matrix_stories - prd_stories):
        violations.append(
            f"dangling story: the matrix references {story}, not a User Story in docs/PRD.md."
        )
    for sub in sorted(matrix_subs - arch_subs):
        violations.append(
            f"unknown subsystem: the matrix references '{sub}', "
            "which is not declared in docs/architecture.md."
        )

    return TraceabilityReport(
        prd_stories=sorted(prd_stories),
        architecture_subsystems=sorted(arch_subs),
        matrix_stories=sorted(matrix_stories),
        matrix_subsystems=sorted(matrix_subs),
        violations=violations,
    )


def audit_files(prd: Path, architecture: Path, traceability: Path) -> TraceabilityReport:
    """Read the three inputs and run the audit. Missing files become clear violations."""
    missing = [str(p) for p in (prd, architecture, traceability) if not p.is_file()]
    if missing:
        return TraceabilityReport(
            violations=[f"required input missing: {m}" for m in missing]
        )
    return audit_traceability(
        prd.read_text(encoding="utf-8"),
        architecture.read_text(encoding="utf-8"),
        traceability.read_text(encoding="utf-8"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint: audit the traceability matrix, print JSON, exit non-zero on any violation."""
    parser = argparse.ArgumentParser(
        description=(
            "Gate the story<->subsystem traceability matrix: fail on orphaned stories, "
            "speculative subsystems, or dangling references."
        )
    )
    parser.add_argument("--prd", default="docs/PRD.md",
                        help="Path to the PRD (default: docs/PRD.md).")
    parser.add_argument(
        "--architecture",
        default="docs/architecture.md",
        help="Path to the architecture doc (default: docs/architecture.md).",
    )
    parser.add_argument(
        "--traceability",
        default="docs/traceability.md",
        help="Path to the traceability matrix (default: docs/traceability.md).",
    )
    args = parser.parse_args(argv)

    report = audit_files(Path(args.prd), Path(args.architecture), Path(args.traceability))
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: traceability audit failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
