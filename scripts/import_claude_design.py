"""Claude Design export importer (advisory UXP input — NOT a gate).

Best-effort, format-tolerant importer that unpacks a Claude Design export ``.zip`` and maps the
design values it discovers (colors, font families, component names) against the frozen Maestro
design system. It emits a *conformance report* — which discovered values are on-brand tokens vs.
off-brand "magic values", and which component names are whitelisted vs. not — plus an optional
draft ``ui-spec.json`` scaffold for the ``ux-design`` persona to complete.

This tool never freezes a contract and never blocks a merge: ``scripts/validate_ui_spec.py``
remains the mechanical authority (``gate-ui``). The importer only turns a pile of generated design
code into a checklist of conformance decisions — off-brand values are *surfaced*, never smuggled
through as tokens. A Claude Design export has no guaranteed schema, so extraction is heuristic over
any HTML/CSS/JSX/TSX/JS/TS/JSON/SVG text entries found in the archive.

Exit codes:
* 0 — archive scanned successfully (report printed; off-brand findings are reported, not failed).
* 2 — usage / IO error (archive missing or corrupt, no importable files, design system unloadable).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_ui_spec import (  # noqa: E402
    DEFAULT_DESIGN_SYSTEM_DIR,
    DesignSystem,
    load_design_system,
)

TEXT_SUFFIXES = frozenset(
    {".html", ".htm", ".css", ".jsx", ".tsx", ".js", ".ts", ".mjs", ".json", ".svg", ".vue"}
)
HEX_PATTERN = re.compile(r"#[0-9a-fA-F]{3,8}")
FONT_FAMILY_PATTERN = re.compile(r"font-?family\s*:\s*([^;{}\n]+)", re.IGNORECASE)
COMPONENT_PATTERN = re.compile(r"<([A-Z][A-Za-z0-9]*)")


@dataclass(frozen=True)
class ImportReport:
    """Conformance report mapping a Claude Design export against the frozen design system."""

    zip_path: str
    files_scanned: list[str] = field(default_factory=list)
    mapped_colors: dict[str, str] = field(default_factory=dict)
    unmapped_colors: list[str] = field(default_factory=list)
    mapped_fonts: dict[str, str] = field(default_factory=dict)
    unmapped_fonts: list[str] = field(default_factory=list)
    whitelisted_components: list[str] = field(default_factory=list)
    non_whitelisted_components: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to a serializable dictionary."""
        return asdict(self)


def _normalize_hex(raw: str) -> str | None:
    """Normalize a hex color to ``#rrggbb`` lowercase, or None if not a 3/6/8-digit hex."""
    digits = raw.lstrip("#").lower()
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    elif len(digits) == 8:
        digits = digits[:6]
    if len(digits) != 6:
        return None
    return f"#{digits}"


def _first_family(declaration: str) -> str:
    """Extract the first (primary) font family from a ``font-family`` declaration value."""
    first = declaration.split(",")[0].strip()
    return first.strip("'\"").strip()


def _extract_colors(text: str) -> set[str]:
    """Extract all normalized hex colors referenced in a text blob."""
    colors: set[str] = set()
    for match in HEX_PATTERN.findall(text):
        normalized = _normalize_hex(match)
        if normalized is not None:
            colors.add(normalized)
    return colors


def _extract_fonts(text: str) -> set[str]:
    """Extract the primary font family of every ``font-family`` / ``fontFamily`` declaration."""
    fonts: set[str] = set()
    for declaration in FONT_FAMILY_PATTERN.findall(text):
        family = _first_family(declaration)
        if family:
            fonts.add(family)
    return fonts


def _extract_components(text: str) -> set[str]:
    """Extract capitalized component names (JSX/TSX opening tags) referenced in a text blob."""
    return set(COMPONENT_PATTERN.findall(text))


def _reverse_color_map(design: DesignSystem) -> dict[str, str]:
    """Map each normalized design-system color value to its ``{color.<name>}`` token reference."""
    reverse: dict[str, str] = {}
    for name, value in design.tokens.get("color", {}).items():
        normalized = _normalize_hex(value)
        if normalized is not None:
            reverse[normalized] = f"{{color.{name}}}"
    return reverse


def _font_token_families(design: DesignSystem) -> dict[str, str]:
    """Map each lowercased font family in the design system to its ``{font.<name>}`` reference."""
    families: dict[str, str] = {}
    for name, value in design.tokens.get("font", {}).items():
        for part in value.split(","):
            family = part.strip().strip("'\"").strip().lower()
            if family:
                families[family] = f"{{font.{name}}}"
    return families


def _read_zip_text_entries(zip_path: str | Path) -> tuple[list[tuple[str, str]] | None, list[str]]:
    """Read importable text entries from a zip archive.

    Reads entry bytes directly from the archive (never extracting to disk, so path traversal /
    zip-slip is impossible). Returns ``(entries, [])`` on success or ``(None, [violation, ...])``.
    """
    path = Path(zip_path)
    if not path.is_file():
        return None, [f"Export archive not found or not a file: '{path}'."]

    entries: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if Path(info.filename).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                raw = archive.read(info.filename)
                entries.append((info.filename, raw.decode("utf-8", errors="replace")))
    except (OSError, zipfile.BadZipFile) as err:
        return None, [f"Failed to read export archive '{path}': {err}"]

    if not entries:
        return None, [
            f"Export archive '{path}' contained no importable text files "
            f"(looked for: {', '.join(sorted(TEXT_SUFFIXES))})."
        ]
    return entries, []


def build_import_report(
    entries: list[tuple[str, str]], design: DesignSystem, *, zip_path: str = ""
) -> ImportReport:
    """Analyze extracted text entries against a design system into a conformance report."""
    colors: set[str] = set()
    fonts: set[str] = set()
    components: set[str] = set()
    for _name, text in entries:
        colors |= _extract_colors(text)
        fonts |= _extract_fonts(text)
        components |= _extract_components(text)

    color_map = _reverse_color_map(design)
    mapped_colors: dict[str, str] = {}
    unmapped_colors: list[str] = []
    for color in sorted(colors):
        token = color_map.get(color)
        if token is not None:
            mapped_colors[color] = token
        else:
            unmapped_colors.append(color)

    font_map = _font_token_families(design)
    mapped_fonts: dict[str, str] = {}
    unmapped_fonts: list[str] = []
    for font in sorted(fonts):
        token = font_map.get(font.lower())
        if token is not None:
            mapped_fonts[font] = token
        else:
            unmapped_fonts.append(font)

    return ImportReport(
        zip_path=zip_path,
        files_scanned=sorted(name for name, _ in entries),
        mapped_colors=mapped_colors,
        unmapped_colors=unmapped_colors,
        mapped_fonts=mapped_fonts,
        unmapped_fonts=unmapped_fonts,
        whitelisted_components=sorted(c for c in components if c in design.components),
        non_whitelisted_components=sorted(c for c in components if c not in design.components),
    )


def build_draft_ui_spec(report: ImportReport) -> dict[str, object]:
    """Build a NON-AUTHORITATIVE draft ui-spec scaffold from a conformance report.

    The scaffold is deliberately incomplete (no user-story mapping, no navigation) so it cannot
    pass ``validate_ui_spec.py`` until the ``ux-design`` persona finishes and conforms it — the
    gate still bites. ``_draft_notes`` records the off-brand decisions the persona must resolve.
    """
    notes: list[str] = [
        "NON-AUTHORITATIVE scaffold from import_claude_design.py. The ux-design persona MUST "
        "complete it (map each screen to PRD user stories, author navigation transitions, and "
        "conform every text style to design tokens) and it MUST pass scripts/validate_ui_spec.py "
        "before it is frozen."
    ]
    if report.unmapped_colors:
        notes.append(
            "Off-brand colors to conform to tokens (or add as tokens): "
            + ", ".join(report.unmapped_colors)
            + "."
        )
    if report.unmapped_fonts:
        notes.append(
            "Off-brand fonts to conform to tokens (or add as tokens): "
            + ", ".join(report.unmapped_fonts)
            + "."
        )
    if report.non_whitelisted_components:
        notes.append(
            "Components outside the whitelist (replace, or extend components.json): "
            + ", ".join(report.non_whitelisted_components)
            + "."
        )
    return {
        "schema": "maestro/ui-spec@1",
        "initial_screen": "imported",
        "screens": [
            {
                "id": "imported",
                "user_stories": [],
                "components": list(report.whitelisted_components),
                "text_styles": [],
                "transitions": [],
            }
        ],
        "_draft_notes": notes,
    }


def import_export_file(
    zip_path: str | Path,
    *,
    design_system_dir: str | Path = DEFAULT_DESIGN_SYSTEM_DIR,
    emit_draft_path: str | Path | None = None,
) -> ImportReport:
    """Import a Claude Design export .zip and return a conformance report.

    Args:
        zip_path: Path to the Claude Design export archive.
        design_system_dir: Design-system directory (defaults to shipped corporate tokens).
        emit_draft_path: When set, write a draft ui-spec scaffold to this path.

    Returns:
        ImportReport. ``violations`` is non-empty when the archive or design system is unusable.
    """
    design, load_violations = load_design_system(design_system_dir)
    if design is None:
        return ImportReport(zip_path=str(zip_path), violations=load_violations)

    entries, read_violations = _read_zip_text_entries(zip_path)
    if entries is None:
        return ImportReport(zip_path=str(zip_path), violations=read_violations)

    report = build_import_report(entries, design, zip_path=str(zip_path))
    if emit_draft_path is not None:
        draft = build_draft_ui_spec(report)
        Path(emit_draft_path).write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the advisory Claude Design export importer."""
    parser = argparse.ArgumentParser(
        description=(
            "Import a Claude Design export .zip and report which discovered "
            "colors/fonts/components are on-brand design tokens vs. off-brand magic values. "
            "Advisory only — "
            "scripts/validate_ui_spec.py (gate-ui) remains the mechanical authority."
        )
    )
    parser.add_argument("archive", help="Path to the Claude Design export .zip archive.")
    parser.add_argument(
        "--design-system",
        default=str(DEFAULT_DESIGN_SYSTEM_DIR),
        help="Design-system directory (tokens.json, components.json, a11y-rules.json).",
    )
    parser.add_argument(
        "--emit-draft",
        default=None,
        help="Write a draft (non-authoritative) ui-spec.json scaffold to this path.",
    )

    args = parser.parse_args(argv)

    report = import_export_file(
        args.archive,
        design_system_dir=args.design_system,
        emit_draft_path=args.emit_draft,
    )
    print(json.dumps(report.to_dict(), indent=2))

    if report.violations:
        print(
            f"ERROR: import failed with {len(report.violations)} problem(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 2

    if args.emit_draft:
        print(
            f"Wrote draft ui-spec scaffold to '{args.emit_draft}'. It is advisory and incomplete — "
            f"complete it, then validate with scripts/validate_ui_spec.py.",
            file=sys.stderr,
        )
    print(
        f"Scanned {len(report.files_scanned)} file(s): "
        f"{len(report.mapped_colors)} on-brand / {len(report.unmapped_colors)} off-brand color(s), "
        f"{len(report.non_whitelisted_components)} non-whitelisted component(s). Advisory only — "
        f"validate_ui_spec.py (gate-ui) is the authority.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
