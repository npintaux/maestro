"""Unit tests for the UI Spec Validator (scripts/validate_ui_spec.py)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_ui_spec import (
    DEFAULT_DESIGN_SYSTEM_DIR,
    DesignSystem,
    UiSpecAuditReport,
    audit_ui_spec,
    audit_ui_spec_file,
    load_design_system,
    main,
)


def _design() -> DesignSystem:
    """A hand-built design system for pure audit_ui_spec tests."""
    return DesignSystem(
        tokens={
            "color": {
                "on-surface": "#111827",
                "surface": "#FFFFFF",
                "black3": "#000",  # 3-char hex, expands to #000000
                "low": "#777777",  # ~4.48:1 on white: fails normal, passes large
                "bad": "notahex",
            },
            "font": {"family-sans": "Inter"},
        },
        components=frozenset({"AppBar", "Button", "Text", "List"}),
        contrast_normal=4.5,
        contrast_large=3.0,
    )


def _spec() -> dict[str, Any]:
    """A minimal valid ui-spec object."""
    return {
        "schema": "maestro/ui-spec@1",
        "initial_screen": "home",
        "screens": [
            {
                "id": "home",
                "user_stories": ["US-1"],
                "components": ["AppBar", "Button"],
                "text_styles": [
                    {
                        "color": "{color.on-surface}",
                        "background": "{color.surface}",
                        "size": "normal",
                    }
                ],
                "transitions": [{"on": "go", "to": "detail"}],
            },
            {
                "id": "detail",
                "user_stories": ["US-2"],
                "components": ["Text"],
                "text_styles": [],
                "transitions": [],
            },
        ],
    }


# --- audit_ui_spec: happy path & structural guards ---------------------------------------------


def test_valid_spec_passes() -> None:
    report = audit_ui_spec(_spec(), _design())
    assert report.is_valid
    assert report.screens_found == ["detail", "home"]
    assert report.user_stories_covered == ["US-1", "US-2"]
    assert report.violations == []


def test_non_dict_spec_fails() -> None:
    report = audit_ui_spec(["not", "a", "dict"], _design())
    assert not report.is_valid
    assert "must be a JSON object" in report.violations[0]


def test_missing_screens_fails() -> None:
    report = audit_ui_spec({"screens": []}, _design())
    assert not report.is_valid
    assert "non-empty 'screens' list" in report.violations[0]


def test_report_to_dict_carries_valid_key() -> None:
    d = audit_ui_spec(_spec(), _design()).to_dict()
    assert d["valid"] is True
    assert "screens_found" in d


# --- zero magic values & contrast --------------------------------------------------------------


def test_raw_color_literal_is_magic_value() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["color"] = "#123456"
    report = audit_ui_spec(spec, _design())
    assert not report.is_valid
    assert any("magic values" in v for v in report.violations)


def test_unknown_background_token_fails() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["background"] = "{color.ghost}"
    report = audit_ui_spec(spec, _design())
    assert any("'background' must be a resolvable" in v for v in report.violations)


def test_wrong_category_token_rejected() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["color"] = "{font.family-sans}"
    report = audit_ui_spec(spec, _design())
    assert any("'color' must be a resolvable" in v for v in report.violations)


def test_low_contrast_normal_text_fails() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["color"] = "{color.low}"
    report = audit_ui_spec(spec, _design())
    assert any("below the WCAG minimum" in v for v in report.violations)


def test_low_contrast_passes_as_large_text() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["color"] = "{color.low}"
    spec["screens"][0]["text_styles"][0]["size"] = "large"
    report = audit_ui_spec(spec, _design())
    assert report.is_valid


def test_default_size_is_normal() -> None:
    spec = _spec()
    del spec["screens"][0]["text_styles"][0]["size"]
    spec["screens"][0]["text_styles"][0]["color"] = "{color.low}"
    report = audit_ui_spec(spec, _design())
    assert any("normal text" in v for v in report.violations)


def test_invalid_size_fails() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["size"] = "huge"
    report = audit_ui_spec(spec, _design())
    assert any("'size' must be one of" in v for v in report.violations)


def test_three_char_hex_token_resolves() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["color"] = "{color.black3}"
    report = audit_ui_spec(spec, _design())
    assert report.is_valid


def test_missing_color_field_is_magic_value() -> None:
    spec = _spec()
    del spec["screens"][0]["text_styles"][0]["color"]
    report = audit_ui_spec(spec, _design())
    assert any("'color' must be a resolvable" in v for v in report.violations)


def test_text_style_not_object_fails() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"] = ["nope"]
    report = audit_ui_spec(spec, _design())
    assert any("must be an object with 'color'" in v for v in report.violations)


def test_token_resolves_to_invalid_hex_fails() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"][0]["color"] = "{color.bad}"
    spec["screens"][0]["text_styles"][0]["background"] = "{color.bad}"
    report = audit_ui_spec(spec, _design())
    assert any("not a valid hex color" in v for v in report.violations)


def test_text_styles_not_list_fails() -> None:
    spec = _spec()
    spec["screens"][0]["text_styles"] = "nope"
    report = audit_ui_spec(spec, _design())
    assert any("'text_styles' must be a list" in v for v in report.violations)


# --- component whitelist -----------------------------------------------------------------------


def test_unknown_component_fails() -> None:
    spec = _spec()
    spec["screens"][0]["components"].append("MagicWidget")
    report = audit_ui_spec(spec, _design())
    assert any("not in the design-system component whitelist" in v for v in report.violations)


def test_components_not_list_fails() -> None:
    spec = _spec()
    spec["screens"][0]["components"] = "AppBar"
    report = audit_ui_spec(spec, _design())
    assert any("'components' must be a list" in v for v in report.violations)


# --- screen structure & ids --------------------------------------------------------------------


def test_screen_not_object_fails() -> None:
    spec = _spec()
    spec["screens"].append("nope")
    report = audit_ui_spec(spec, _design())
    assert any("must be an object" in v for v in report.violations)


def test_screen_missing_id_fails() -> None:
    spec = _spec()
    del spec["screens"][0]["id"]
    report = audit_ui_spec(spec, _design())
    assert any("missing a non-empty string 'id'" in v for v in report.violations)


def test_duplicate_screen_id_fails() -> None:
    spec = _spec()
    dup = copy.deepcopy(spec["screens"][1])
    dup["id"] = "home"
    spec["screens"].append(dup)
    report = audit_ui_spec(spec, _design())
    assert any("Duplicate screen id 'home'" in v for v in report.violations)


def test_all_screens_invalid_skips_navigation() -> None:
    spec = {"initial_screen": "home", "screens": [{"components": []}]}
    report = audit_ui_spec(spec, _design())
    assert not report.is_valid
    assert report.screens_found == []
    # Navigation checks never ran, so no 'initial_screen' violation was appended.
    assert all("initial_screen" not in v for v in report.violations)


# --- user-story traceability -------------------------------------------------------------------


def test_screen_without_stories_fails() -> None:
    spec = _spec()
    spec["screens"][0]["user_stories"] = []
    report = audit_ui_spec(spec, _design())
    assert any("at least one PRD User Story" in v for v in report.violations)


def test_invalid_story_id_fails() -> None:
    spec = _spec()
    spec["screens"][0]["user_stories"] = ["US-1", "bogus"]
    report = audit_ui_spec(spec, _design())
    assert any("is not a valid 'US-N' identifier" in v for v in report.violations)


def test_story_not_in_prd_fails() -> None:
    report = audit_ui_spec(_spec(), _design(), prd_text="# PRD\n## US-1 only\n")
    assert any("not defined in docs/PRD.md" in v for v in report.violations)


def test_stories_all_defined_in_prd_passes() -> None:
    report = audit_ui_spec(_spec(), _design(), prd_text="US-1 and US-2 are here")
    assert report.is_valid


# --- navigation FSM ----------------------------------------------------------------------------


def test_transition_to_unknown_screen_fails() -> None:
    spec = _spec()
    spec["screens"][0]["transitions"][0]["to"] = "ghost"
    report = audit_ui_spec(spec, _design())
    assert any("targets unknown screen" in v for v in report.violations)


def test_initial_screen_undefined_fails() -> None:
    spec = _spec()
    spec["initial_screen"] = "ghost"
    report = audit_ui_spec(spec, _design())
    assert any("is not a defined screen id" in v for v in report.violations)


def test_unreachable_screen_fails() -> None:
    spec = _spec()
    spec["screens"][0]["transitions"] = []  # nothing reaches 'detail'
    report = audit_ui_spec(spec, _design())
    assert any("unreachable from the initial screen" in v for v in report.violations)


def test_transitions_not_list_fails() -> None:
    spec = _spec()
    spec["screens"][0]["transitions"] = "nope"
    spec["screens"][1]["user_stories"] = ["US-2"]
    spec["screens"] = [spec["screens"][0]]  # single screen so no orphan noise
    report = audit_ui_spec(spec, _design())
    assert any("'transitions' must be a list" in v for v in report.violations)


def test_transition_not_object_fails() -> None:
    spec = _spec()
    spec["screens"][0]["transitions"] = ["nope"]
    spec["screens"] = [spec["screens"][0]]
    report = audit_ui_spec(spec, _design())
    assert any("transition that is not an object" in v for v in report.violations)


def test_transition_missing_trigger_fails() -> None:
    spec = _spec()
    spec["screens"][0]["transitions"] = [{"to": "detail"}]
    report = audit_ui_spec(spec, _design())
    assert any("missing a string 'on'" in v for v in report.violations)


def test_duplicate_trigger_fails() -> None:
    spec = _spec()
    spec["screens"][0]["transitions"] = [
        {"on": "go", "to": "detail"},
        {"on": "go", "to": "detail"},
    ]
    report = audit_ui_spec(spec, _design())
    assert any("duplicate transition trigger" in v for v in report.violations)


# --- load_design_system ------------------------------------------------------------------------


def _write_ds(
    root: Path,
    *,
    tokens: Any = "default",
    components: Any = "default",
    a11y: Any = "default",
) -> Path:
    """Write a design-system directory; pass None to omit a file, or an object to override."""
    root.mkdir(parents=True, exist_ok=True)
    if tokens == "default":
        tokens = {"color": {"on-surface": "#111827", "surface": "#FFFFFF"}, "font": {"s": "Inter"}}
    if components == "default":
        components = {"components": ["AppBar", "Button", "Text"]}
    if a11y == "default":
        a11y = {"contrast": {"normal-text": 4.5, "large-text": 3.0}}
    files = (("tokens.json", tokens), ("components.json", components), ("a11y-rules.json", a11y))
    for name, obj in files:
        if obj is not None:
            (root / name).write_text(json.dumps(obj), encoding="utf-8")
    return root


def test_load_design_system_valid() -> None:
    design, violations = load_design_system(DEFAULT_DESIGN_SYSTEM_DIR)
    assert violations == []
    assert design is not None
    assert "brand-primary" in design.tokens["color"]
    assert "Button" in design.components


def test_load_missing_files(tmp_path: Path) -> None:
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert len(violations) == 3
    assert all("not found" in v for v in violations)


def test_load_malformed_json(tmp_path: Path) -> None:
    _write_ds(tmp_path)
    (tmp_path / "tokens.json").write_text("{ not json", encoding="utf-8")
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("Failed to parse" in v for v in violations)


def test_load_non_object_file(tmp_path: Path) -> None:
    _write_ds(tmp_path, tokens=[1, 2, 3])
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("must contain a JSON object" in v for v in violations)


def test_load_no_color_tokens(tmp_path: Path) -> None:
    _write_ds(tmp_path, tokens={"font": {"s": "Inter"}})
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("no 'color' tokens" in v for v in violations)


def test_load_skips_non_dict_category_and_non_string_values(tmp_path: Path) -> None:
    _write_ds(
        tmp_path,
        tokens={
            "color": {"on-surface": "#111827", "surface": "#FFFFFF", "num": 5},
            "weird": "not-a-dict",
        },
    )
    design, violations = load_design_system(tmp_path)
    assert violations == []
    assert design is not None
    assert "num" not in design.tokens["color"]
    assert "weird" not in design.tokens


def test_load_components_not_list(tmp_path: Path) -> None:
    _write_ds(tmp_path, components={"components": "AppBar"})
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("non-empty 'components' list" in v for v in violations)


def test_load_contrast_not_dict(tmp_path: Path) -> None:
    _write_ds(tmp_path, a11y={"contrast": "nope"})
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("missing a 'contrast' block" in v for v in violations)


def test_load_non_numeric_threshold(tmp_path: Path) -> None:
    _write_ds(tmp_path, a11y={"contrast": {"normal-text": "x", "large-text": 3.0}})
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("must be a number" in v for v in violations)


def test_load_bool_threshold_rejected(tmp_path: Path) -> None:
    _write_ds(tmp_path, a11y={"contrast": {"normal-text": True, "large-text": 3.0}})
    design, violations = load_design_system(tmp_path)
    assert design is None
    assert any("'contrast.normal-text' must be a number" in v for v in violations)


# --- audit_ui_spec_file & CLI ------------------------------------------------------------------


def test_file_not_found(tmp_path: Path) -> None:
    report = audit_ui_spec_file(tmp_path / "nope.json")
    assert not report.is_valid
    assert "not found" in report.violations[0]


def test_file_bad_design_system(tmp_path: Path) -> None:
    (tmp_path / "ui-spec.json").write_text(json.dumps(_spec()), encoding="utf-8")
    report = audit_ui_spec_file(tmp_path / "ui-spec.json", design_system_dir=tmp_path / "missing")
    assert not report.is_valid
    assert any("not found" in v for v in report.violations)


def test_file_malformed_ui_spec(tmp_path: Path) -> None:
    ds = _write_ds(tmp_path / "ds")
    (tmp_path / "ui-spec.json").write_text("{ not json", encoding="utf-8")
    report = audit_ui_spec_file(tmp_path / "ui-spec.json", design_system_dir=ds)
    assert not report.is_valid
    assert any("Failed to read or parse" in v for v in report.violations)


def test_file_prd_not_found(tmp_path: Path) -> None:
    ds = _write_ds(tmp_path / "ds")
    (tmp_path / "ui-spec.json").write_text(json.dumps(_spec()), encoding="utf-8")
    report = audit_ui_spec_file(
        tmp_path / "ui-spec.json", design_system_dir=ds, prd_path=tmp_path / "nope.md"
    )
    assert not report.is_valid
    assert any("PRD file not found" in v for v in report.violations)


def test_file_valid_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "ui-spec.json").write_text(json.dumps(_spec()), encoding="utf-8")
    prd = tmp_path / "PRD.md"
    prd.write_text("US-1 and US-2", encoding="utf-8")
    report = audit_ui_spec_file(tmp_path / "ui-spec.json", prd_path=prd)
    assert report.is_valid
    assert report.file_path.endswith("ui-spec.json")


def test_main_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "ui-spec.json").write_text(json.dumps(_spec()), encoding="utf-8")
    code = main([str(tmp_path / "ui-spec.json")])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is True


def test_main_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = _spec()
    spec["screens"][0]["components"].append("MagicWidget")
    (tmp_path / "ui-spec.json").write_text(json.dumps(spec), encoding="utf-8")
    code = main([str(tmp_path / "ui-spec.json")])
    assert code == 1
    captured = capsys.readouterr()
    assert "validation failed" in captured.err


def test_report_dataclass_default_fields() -> None:
    report = UiSpecAuditReport(is_valid=True, file_path="x")
    assert report.screens_found == []
    assert report.violations == []
