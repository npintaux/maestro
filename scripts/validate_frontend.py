"""Front-end conformance validator for a subsystem's Flask + Jinja/HTML/CSS UI.

Mechanically validates that an *implemented* front-end conforms to the subsystem's frozen
``ui-spec.json`` and the design system, so a front-end implementer (and any generative aid such as a
Stitch MCP call) cannot smuggle off-brand or off-spec UI past the gate:

* Token materialization: ``frontend/static/tokens.css`` must exist and be byte-identical to the
  CSS custom properties generated from ``tokens.json`` (the single source of truth for colors,
  fonts, sizes, spacing, radii). Regenerate it — never hand-edit.
* Zero magic colors: no raw ``#hex`` / ``rgb()`` / ``hsl()`` color literal may appear in any project
  CSS except the generated ``tokens.css``; every color must be a ``var(--color-<name>)`` reference.
* Screen bijection: the set of screen templates ``frontend/templates/screens/<id>.html`` must equal
  the set of screen ids in ``ui-spec.json`` — no missing screens, no undeclared ("smuggled") ones.
* Navigation wiring: for every transition a screen declares in ``ui-spec.json``, that screen's
  template must actually link to the target via ``url_for('<target>')`` — the nav FSM is wired.

The frozen ``ui-spec.json`` (already enforced by ``gate-ui``) is the contract; this validator checks
the code against it. It backs the ``gate-frontend`` stage and is advisory of nothing — it bites.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_ui_spec import (  # noqa: E402
    DEFAULT_DESIGN_SYSTEM_DIR,
    DesignSystem,
    load_design_system,
)

TOKENS_CSS_NAME = "tokens.css"
MAGIC_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{3,8}|\b(?:rgba?|hsla?)\s*\(")


@dataclass(frozen=True)
class FrontendAuditReport:
    """Audit report for a subsystem front-end conformance validation."""

    is_valid: bool
    subsystem_path: str
    screens_found: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def generate_tokens_css(design: DesignSystem) -> str:
    """Render the design system's tokens as deterministic CSS custom properties.

    The front-end implementer writes exactly this output to ``frontend/static/tokens.css``; the gate
    regenerates it and requires a byte-for-byte match, keeping tokens.json the sole source of truth.
    """
    lines = [":root {"]
    for category in sorted(design.tokens):
        for name in sorted(design.tokens[category]):
            lines.append(f"  --{category}-{name}: {design.tokens[category][name]};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _extract_spec_screens(spec: Any) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Extract ``(screen_id, transition_targets)`` pairs from a parsed ui-spec.

    Returns ``(screens, violations)``. The ui-spec has already passed ``gate-ui``, so this parses
    defensively but does not re-validate structure.
    """
    screens_raw = spec.get("screens") if isinstance(spec, dict) else None
    if not isinstance(screens_raw, list) or not screens_raw:
        return [], ["ui-spec.json defines no 'screens'; cannot validate the front-end against it."]

    screens: list[tuple[str, list[str]]] = []
    for screen in screens_raw:
        if not isinstance(screen, dict):
            continue
        screen_id = screen.get("id")
        if not isinstance(screen_id, str) or not screen_id:
            continue
        targets: list[str] = []
        transitions = screen.get("transitions", [])
        if isinstance(transitions, list):
            for transition in transitions:
                target = transition.get("to") if isinstance(transition, dict) else None
                if isinstance(target, str) and target:
                    targets.append(target)
        screens.append((screen_id, targets))
    return screens, []


def _audit_tokens_css(frontend_dir: Path, design: DesignSystem) -> list[str]:
    """Verify frontend/static/tokens.css exists and matches the generated token CSS exactly."""
    tokens_css = frontend_dir / "static" / TOKENS_CSS_NAME
    if not tokens_css.is_file():
        return [
            f"Generated token stylesheet is missing: '{tokens_css}'. Regenerate it with "
            f"`validate_frontend.py <subsystem> --emit-tokens-css {tokens_css}`."
        ]
    if tokens_css.read_text(encoding="utf-8") != generate_tokens_css(design):
        return [
            f"'{tokens_css}' is out of sync with the design system tokens. Do not hand-edit it; "
            f"regenerate it from tokens.json."
        ]
    return []


def _audit_magic_colors(frontend_dir: Path) -> list[str]:
    """Deny raw color literals in any project CSS except the generated tokens.css."""
    violations: list[str] = []
    static_dir = frontend_dir / "static"
    for css_file in sorted(static_dir.rglob("*.css")):
        if css_file.name == TOKENS_CSS_NAME:
            continue
        rel = css_file.relative_to(frontend_dir)
        for lineno, line in enumerate(css_file.read_text(encoding="utf-8").splitlines(), start=1):
            if MAGIC_COLOR_PATTERN.search(line):
                violations.append(
                    f"{rel}:{lineno} uses a raw color literal; use a var(--color-<name>) token "
                    f"instead (colors must resolve to the design system)."
                )
    return violations


def _audit_screens_and_navigation(
    frontend_dir: Path, screens: list[tuple[str, list[str]]]
) -> tuple[list[str], list[str]]:
    """Check the template↔spec screen bijection and that declared transitions are wired.

    Returns ``(screen_ids_found, violations)``.
    """
    violations: list[str] = []
    screens_dir = frontend_dir / "templates" / "screens"
    template_ids = {p.stem for p in screens_dir.glob("*.html")} if screens_dir.is_dir() else set()
    spec_ids = {sid for sid, _ in screens}

    for missing in sorted(spec_ids - template_ids):
        violations.append(
            f"Screen '{missing}' in ui-spec.json has no template "
            f"'templates/screens/{missing}.html'."
        )
    for orphan in sorted(template_ids - spec_ids):
        violations.append(
            f"Template 'templates/screens/{orphan}.html' has no matching screen in ui-spec.json "
            f"(undeclared screen)."
        )

    for screen_id, targets in screens:
        template = screens_dir / f"{screen_id}.html"
        if not template.is_file():
            continue
        content = template.read_text(encoding="utf-8")
        for target in targets:
            link = re.compile(rf"url_for\(\s*['\"]{re.escape(target)}['\"]")
            if not link.search(content):
                violations.append(
                    f"Screen '{screen_id}' declares a transition to '{target}' but its template "
                    f"does not link to it via url_for('{target}')."
                )
    return sorted(spec_ids), violations


def audit_frontend(
    frontend_dir: Path, spec: Any, design: DesignSystem, *, subsystem_path: str = ""
) -> FrontendAuditReport:
    """Audit an implemented front-end tree against a frozen ui-spec and design system."""
    screens, spec_violations = _extract_spec_screens(spec)
    if spec_violations:
        return FrontendAuditReport(
            is_valid=False, subsystem_path=subsystem_path, violations=spec_violations
        )

    violations: list[str] = []
    violations.extend(_audit_tokens_css(frontend_dir, design))
    violations.extend(_audit_magic_colors(frontend_dir))
    screen_ids, nav_violations = _audit_screens_and_navigation(frontend_dir, screens)
    violations.extend(nav_violations)

    return FrontendAuditReport(
        is_valid=not violations,
        subsystem_path=subsystem_path,
        screens_found=screen_ids,
        violations=violations,
    )


def audit_frontend_dir(
    subsystem_dir: str | Path,
    *,
    design_system_dir: str | Path = DEFAULT_DESIGN_SYSTEM_DIR,
) -> FrontendAuditReport:
    """Load a subsystem's ui-spec/design system from disk and audit its front-end tree.

    Args:
        subsystem_dir: Path to ``src/modules/<subsystem>`` (contains ``ui-spec.json`` and
            ``frontend/``).
        design_system_dir: Directory of the design system (defaults to shipped corporate tokens).

    Returns:
        FrontendAuditReport.
    """
    subsystem = Path(subsystem_dir)
    design, load_violations = load_design_system(design_system_dir)
    if design is None:
        return FrontendAuditReport(
            is_valid=False, subsystem_path=str(subsystem), violations=load_violations
        )

    ui_spec_path = subsystem / "ui-spec.json"
    if not ui_spec_path.is_file():
        return FrontendAuditReport(
            is_valid=False,
            subsystem_path=str(subsystem),
            violations=[f"ui-spec.json not found: '{ui_spec_path}'. Freeze it via gate-ui first."],
        )

    try:
        spec = json.loads(ui_spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        return FrontendAuditReport(
            is_valid=False,
            subsystem_path=str(subsystem),
            violations=[f"Failed to read or parse ui-spec.json: {err}"],
        )

    frontend_dir = subsystem / "frontend"
    if not frontend_dir.is_dir():
        return FrontendAuditReport(
            is_valid=False,
            subsystem_path=str(subsystem),
            violations=[f"Front-end directory not found: '{frontend_dir}'."],
        )

    return audit_frontend(frontend_dir, spec, design, subsystem_path=str(subsystem))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for front-end conformance validation (gate-frontend)."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate a subsystem's implemented Flask/Jinja/CSS front-end against its frozen "
            "ui-spec.json and design system: token-materialization sync, zero magic colors, screen "
            "bijection, and navigation wiring."
        )
    )
    parser.add_argument("subsystem", help="Path to src/modules/<subsystem>.")
    parser.add_argument(
        "--design-system",
        default=str(DEFAULT_DESIGN_SYSTEM_DIR),
        help="Design-system directory (tokens.json, components.json, a11y-rules.json).",
    )
    parser.add_argument(
        "--emit-tokens-css",
        default=None,
        help="Generate the canonical tokens.css from the design system to this path, then exit.",
    )

    args = parser.parse_args(argv)

    if args.emit_tokens_css is not None:
        design, load_violations = load_design_system(args.design_system)
        if design is None:
            for v in load_violations:
                print(f"  - {v}", file=sys.stderr)
            return 2
        out = Path(args.emit_tokens_css)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(generate_tokens_css(design), encoding="utf-8")
        print(f"Wrote generated token stylesheet to '{out}'.", file=sys.stderr)
        return 0

    report = audit_frontend_dir(args.subsystem, design_system_dir=args.design_system)
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: front-end validation failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
