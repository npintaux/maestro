"""UI Spec Validator for frozen ui-spec.json subsystem UI contracts.

Mechanically validates a subsystem's ``ui-spec.json`` against a frozen design system so a
front-end implementer (and any generative aid such as a Stitch MCP call) cannot smuggle
off-brand or inaccessible UI past the gate:

* Zero magic values: every color/font/size/space a screen references must be a ``{category.name}``
  token that resolves in the design system's ``tokens.json`` (raw hex/px literals are denied).
* Component whitelist: every component a screen composes must appear in ``components.json``.
* WCAG contrast: every text style's foreground/background token pair must meet the AA ratio in
  ``a11y-rules.json`` (4.5:1 normal, 3.0:1 large) computed from the resolved token colors.
* Navigation-FSM completeness: the initial screen exists, every transition targets a defined
  screen, every screen is reachable, screen ids are unique, and triggers are unambiguous.
* User-story traceability: every screen maps to at least one PRD User Story; with ``--prd`` each
  referenced story must be defined in ``docs/PRD.md``.

The design system ships as corporate defaults in ``resources/design-system/`` and is overridable
per project via ``--design-system``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TOKEN_REF_PATTERN = re.compile(r"^\{([a-z0-9-]+)\.([a-z0-9-]+)\}$")
HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
USER_STORY_PATTERN = re.compile(r"\bUS-\d+\b")
VALID_TEXT_SIZES = ("normal", "large")

DEFAULT_DESIGN_SYSTEM_DIR = Path(__file__).resolve().parent.parent / "resources" / "design-system"


@dataclass(frozen=True)
class DesignSystem:
    """A loaded, frozen design system used as the token/component/a11y authority."""

    tokens: dict[str, dict[str, str]]
    components: frozenset[str]
    contrast_normal: float
    contrast_large: float


@dataclass(frozen=True)
class UiSpecAuditReport:
    """Detailed audit report for a subsystem ui-spec.json validation."""

    is_valid: bool
    file_path: str
    screens_found: list[str] = field(default_factory=list)
    user_stories_covered: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def _relative_luminance(hex_color: str) -> float:
    """Compute the WCAG relative luminance of a ``#RGB`` or ``#RRGGBB`` color."""
    raw = hex_color.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    channels = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Compute the WCAG contrast ratio between two hex colors."""
    lum1 = _relative_luminance(fg_hex)
    lum2 = _relative_luminance(bg_hex)
    lighter, darker = max(lum1, lum2), min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def load_design_system(design_system_dir: str | Path) -> tuple[DesignSystem | None, list[str]]:
    """Load and validate the tokens/components/a11y files from a design-system directory.

    Args:
        design_system_dir: Directory containing tokens.json, components.json, a11y-rules.json.

    Returns:
        A tuple of (DesignSystem or None, list of load violations). The DesignSystem is None
        whenever any violation is present.
    """
    root = Path(design_system_dir)
    violations: list[str] = []

    tokens_raw = _load_json(root / "tokens.json", violations)
    components_raw = _load_json(root / "components.json", violations)
    a11y_raw = _load_json(root / "a11y-rules.json", violations)
    if violations:
        return None, violations

    tokens: dict[str, dict[str, str]] = {}
    for category, entries in tokens_raw.items():
        if category in {"schema", "description"}:
            continue
        if not isinstance(entries, dict):
            continue
        tokens[category] = {
            name: value for name, value in entries.items() if isinstance(value, str)
        }
    if "color" not in tokens or not tokens["color"]:
        violations.append("Design system tokens.json defines no 'color' tokens.")

    components_list = components_raw.get("components")
    if not isinstance(components_list, list) or not components_list:
        violations.append("Design system components.json has no non-empty 'components' list.")
        components_list = []

    contrast = a11y_raw.get("contrast")
    contrast_normal = 4.5
    contrast_large = 3.0
    if not isinstance(contrast, dict):
        violations.append("Design system a11y-rules.json is missing a 'contrast' block.")
    else:
        contrast_normal = _read_threshold(contrast, "normal-text", violations)
        contrast_large = _read_threshold(contrast, "large-text", violations)

    if violations:
        return None, violations

    design = DesignSystem(
        tokens=tokens,
        components=frozenset(str(c) for c in components_list),
        contrast_normal=contrast_normal,
        contrast_large=contrast_large,
    )
    return design, []


def _read_threshold(contrast: dict[str, Any], key: str, violations: list[str]) -> float:
    """Read a numeric contrast threshold, recording a violation when missing or non-numeric."""
    value = contrast.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        violations.append(f"Design system a11y-rules.json 'contrast.{key}' must be a number.")
        return 0.0
    return float(value)


def _load_json(path: Path, violations: list[str]) -> dict[str, Any]:
    """Load a JSON object file, recording a violation on any failure. Returns {} on failure."""
    if not path.is_file():
        violations.append(f"Design system file not found: '{path}'.")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        violations.append(f"Failed to parse '{path}': {err}")
        return {}
    if not isinstance(data, dict):
        violations.append(f"Design system file '{path}' must contain a JSON object.")
        return {}
    return data


def _resolve_token(ref: Any, design: DesignSystem, expected_category: str | None) -> str | None:
    """Resolve a ``{category.name}`` reference to its token value, or None if invalid.

    Args:
        ref: The candidate reference (should be a ``{category.name}`` string).
        design: The loaded design system.
        expected_category: If set, the reference must belong to this category.

    Returns:
        The resolved token value, or None when the reference is a magic value / unresolved /
        in the wrong category.
    """
    if not isinstance(ref, str):
        return None
    match = TOKEN_REF_PATTERN.match(ref)
    if match is None:
        return None
    category, name = match.group(1), match.group(2)
    if expected_category is not None and category != expected_category:
        return None
    return design.tokens.get(category, {}).get(name)


def _audit_text_style(style: Any, screen_id: str, index: int, design: DesignSystem) -> list[str]:
    """Validate a single text style's color/background tokens and WCAG contrast."""
    tag = f"Screen '{screen_id}' text style #{index}"
    if not isinstance(style, dict):
        return [f"{tag} must be an object with 'color', 'background', and 'size'."]

    violations: list[str] = []
    fg = _resolve_token(style.get("color"), design, "color")
    bg = _resolve_token(style.get("background"), design, "color")
    if fg is None:
        violations.append(
            f"{tag} 'color' must be a resolvable '{{color.<name>}}' token, got "
            f"{style.get('color')!r} (raw values and unknown tokens are magic values)."
        )
    if bg is None:
        violations.append(
            f"{tag} 'background' must be a resolvable '{{color.<name>}}' token, got "
            f"{style.get('background')!r}."
        )

    size = style.get("size", "normal")
    if size not in VALID_TEXT_SIZES:
        violations.append(f"{tag} 'size' must be one of {VALID_TEXT_SIZES}, got {size!r}.")
        return violations

    if fg is None or bg is None:
        return violations
    if not HEX_COLOR_PATTERN.match(fg) or not HEX_COLOR_PATTERN.match(bg):
        violations.append(f"{tag} references a color token whose value is not a valid hex color.")
        return violations

    threshold = design.contrast_large if size == "large" else design.contrast_normal
    ratio = _contrast_ratio(fg, bg)
    if ratio < threshold:
        violations.append(
            f"{tag} contrast {ratio:.2f}:1 is below the WCAG minimum {threshold:.1f}:1 "
            f"for {size} text."
        )
    return violations


def _audit_screen(
    screen: Any, design: DesignSystem, defined_stories: set[str] | None
) -> tuple[str | None, list[str], list[str]]:
    """Validate one screen. Returns (screen_id, user_stories, violations)."""
    if not isinstance(screen, dict):
        return None, [], ["Each entry in 'screens' must be an object."]

    violations: list[str] = []
    screen_id = screen.get("id")
    if not isinstance(screen_id, str) or not screen_id:
        return None, [], ["A screen is missing a non-empty string 'id'."]

    components = screen.get("components", [])
    if not isinstance(components, list):
        violations.append(f"Screen '{screen_id}' 'components' must be a list.")
    else:
        for comp in components:
            if comp not in design.components:
                violations.append(
                    f"Screen '{screen_id}' uses component {comp!r} which is not in the "
                    f"design-system component whitelist."
                )

    text_styles = screen.get("text_styles", [])
    if not isinstance(text_styles, list):
        violations.append(f"Screen '{screen_id}' 'text_styles' must be a list.")
    else:
        for i, style in enumerate(text_styles):
            violations.extend(_audit_text_style(style, screen_id, i, design))

    stories = screen.get("user_stories", [])
    story_list: list[str] = []
    if not isinstance(stories, list) or not stories:
        violations.append(
            f"Screen '{screen_id}' must map to at least one PRD User Story via 'user_stories'."
        )
    else:
        for story in stories:
            if not isinstance(story, str) or not USER_STORY_PATTERN.fullmatch(story):
                violations.append(
                    f"Screen '{screen_id}' user story {story!r} is not a valid 'US-N' identifier."
                )
                continue
            story_list.append(story)
            if defined_stories is not None and story not in defined_stories:
                violations.append(
                    f"Screen '{screen_id}' maps to {story}, which is not defined in docs/PRD.md."
                )

    return screen_id, story_list, violations


def _audit_navigation(
    screens: list[dict[str, Any]], screen_ids: list[str], initial_screen: Any
) -> list[str]:
    """Validate transition targets, trigger uniqueness, initial screen, and reachability."""
    violations: list[str] = []
    id_set = set(screen_ids)
    adjacency: dict[str, list[str]] = {sid: [] for sid in screen_ids}

    for screen in screens:
        screen_id = screen["id"]
        transitions = screen.get("transitions", [])
        if not isinstance(transitions, list):
            violations.append(f"Screen '{screen_id}' 'transitions' must be a list.")
            continue
        seen_triggers: set[str] = set()
        for transition in transitions:
            if not isinstance(transition, dict):
                violations.append(f"Screen '{screen_id}' has a transition that is not an object.")
                continue
            trigger = transition.get("on")
            target = transition.get("to")
            if not isinstance(trigger, str) or not trigger:
                violations.append(f"Screen '{screen_id}' has a transition missing a string 'on'.")
            elif trigger in seen_triggers:
                violations.append(
                    f"Screen '{screen_id}' declares duplicate transition trigger {trigger!r}."
                )
            else:
                seen_triggers.add(trigger)
            if not isinstance(target, str) or target not in id_set:
                violations.append(
                    f"Screen '{screen_id}' transition {trigger!r} targets unknown screen "
                    f"{target!r}."
                )
            elif isinstance(target, str):
                adjacency[screen_id].append(target)

    if not isinstance(initial_screen, str) or initial_screen not in id_set:
        violations.append(f"'initial_screen' {initial_screen!r} is not a defined screen id.")
        return violations

    reachable = _reachable_from(initial_screen, adjacency)
    for orphan in sorted(id_set - reachable):
        violations.append(f"Screen '{orphan}' is unreachable from the initial screen.")
    return violations


def _reachable_from(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    """Breadth-first set of screen ids reachable from ``start``."""
    reachable: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    return reachable


def audit_ui_spec(
    spec: Any, design: DesignSystem, *, prd_text: str | None = None
) -> UiSpecAuditReport:
    """Audit a parsed ui-spec object against a loaded design system.

    Args:
        spec: The parsed ui-spec.json object.
        design: The loaded design system authority.
        prd_text: Optional PRD text; when given, referenced user stories must be defined in it.

    Returns:
        UiSpecAuditReport.
    """
    if not isinstance(spec, dict):
        return UiSpecAuditReport(
            is_valid=False,
            file_path="",
            violations=["ui-spec root document must be a JSON object."],
        )

    screens_raw = spec.get("screens")
    if not isinstance(screens_raw, list) or not screens_raw:
        return UiSpecAuditReport(
            is_valid=False,
            file_path="",
            violations=["ui-spec must define a non-empty 'screens' list."],
        )

    defined_stories: set[str] | None = None
    if prd_text is not None:
        defined_stories = set(USER_STORY_PATTERN.findall(prd_text))

    violations: list[str] = []
    valid_screens: list[dict[str, Any]] = []
    screen_ids: list[str] = []
    stories_covered: set[str] = set()
    seen_ids: set[str] = set()

    for screen in screens_raw:
        screen_id, stories, screen_violations = _audit_screen(screen, design, defined_stories)
        violations.extend(screen_violations)
        if screen_id is None:
            continue
        if screen_id in seen_ids:
            violations.append(f"Duplicate screen id '{screen_id}'.")
            continue
        seen_ids.add(screen_id)
        screen_ids.append(screen_id)
        valid_screens.append(screen)
        stories_covered.update(stories)

    if screen_ids:
        violations.extend(_audit_navigation(valid_screens, screen_ids, spec.get("initial_screen")))

    return UiSpecAuditReport(
        is_valid=not violations,
        file_path="",
        screens_found=sorted(screen_ids),
        user_stories_covered=sorted(stories_covered),
        violations=violations,
    )


def audit_ui_spec_file(
    ui_spec_path: str | Path,
    *,
    design_system_dir: str | Path = DEFAULT_DESIGN_SYSTEM_DIR,
    prd_path: str | Path | None = None,
) -> UiSpecAuditReport:
    """Read a ui-spec.json (and its design system) from disk and audit it.

    Args:
        ui_spec_path: Path to the subsystem's ui-spec.json.
        design_system_dir: Directory of the design system (defaults to shipped corporate tokens).
        prd_path: Optional path to docs/PRD.md for user-story cross-checking.

    Returns:
        UiSpecAuditReport.
    """
    path = Path(ui_spec_path)
    if not path.is_file():
        return UiSpecAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"ui-spec file not found or not a valid file: '{path}'."],
        )

    design, load_violations = load_design_system(design_system_dir)
    if design is None:
        return UiSpecAuditReport(is_valid=False, file_path=str(path), violations=load_violations)

    try:
        content = path.read_text(encoding="utf-8")
        spec = json.loads(content)
    except (OSError, json.JSONDecodeError) as err:
        return UiSpecAuditReport(
            is_valid=False,
            file_path=str(path),
            violations=[f"Failed to read or parse ui-spec: {err}"],
        )

    prd_text: str | None = None
    if prd_path is not None:
        prd_file = Path(prd_path)
        if not prd_file.is_file():
            return UiSpecAuditReport(
                is_valid=False,
                file_path=str(path),
                violations=[f"PRD file not found: '{prd_file}'."],
            )
        prd_text = prd_file.read_text(encoding="utf-8")

    report = audit_ui_spec(spec, design, prd_text=prd_text)
    return UiSpecAuditReport(
        is_valid=report.is_valid,
        file_path=str(path),
        screens_found=report.screens_found,
        user_stories_covered=report.user_stories_covered,
        violations=report.violations,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for ui-spec.json validation against the design system."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate a subsystem's ui-spec.json against a frozen design system: zero magic "
            "values, component whitelist, WCAG contrast, navigation completeness, and PRD "
            "user-story traceability."
        )
    )
    parser.add_argument("file", help="Path to the ui-spec.json to validate.")
    parser.add_argument(
        "--design-system",
        default=str(DEFAULT_DESIGN_SYSTEM_DIR),
        help="Design-system directory (tokens.json, components.json, a11y-rules.json).",
    )
    parser.add_argument(
        "--prd",
        default=None,
        help="Optional docs/PRD.md path to cross-check referenced user stories.",
    )

    args = parser.parse_args(argv)

    report = audit_ui_spec_file(args.file, design_system_dir=args.design_system, prd_path=args.prd)
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: ui-spec validation failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
