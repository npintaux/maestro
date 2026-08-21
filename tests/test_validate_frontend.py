"""Tests for scripts/validate_frontend.py (the gate-frontend conformance validator)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_frontend import (
    audit_frontend,
    audit_frontend_dir,
    generate_tokens_css,
    main,
)
from scripts.validate_ui_spec import load_design_system

# --- fixtures / builders ---------------------------------------------------------------------


def _write_design_system(root: Path) -> Path:
    """Write a minimal but valid design-system directory and return its path."""
    ds = root / "design-system"
    ds.mkdir()
    (ds / "tokens.json").write_text(
        json.dumps(
            {
                "schema": "maestro/design-tokens@1",
                "color": {"primary": "#1A56DB", "surface": "#FFFFFF", "on-surface": "#111827"},
                "font": {"sans": "Inter"},
            }
        ),
        encoding="utf-8",
    )
    (ds / "components.json").write_text(
        json.dumps({"components": ["AppBar", "Button", "Text"]}), encoding="utf-8"
    )
    (ds / "a11y-rules.json").write_text(
        json.dumps({"contrast": {"normal-text": 4.5, "large-text": 3.0}}), encoding="utf-8"
    )
    return ds


_SPEC = {
    "schema": "maestro/ui-spec@1",
    "initial_screen": "home",
    "screens": [
        {"id": "home", "transitions": [{"on": "go", "to": "detail"}]},
        {"id": "detail", "transitions": []},
    ],
}


def _build_subsystem(root: Path, ds: Path, *, spec: object = _SPEC) -> Path:
    """Build a conformant subsystem front-end tree under root and return the subsystem dir."""
    subsystem = root / "modules" / "cart"
    frontend = subsystem / "frontend"
    (frontend / "static").mkdir(parents=True)
    (frontend / "templates" / "screens").mkdir(parents=True)

    subsystem.joinpath("ui-spec.json").write_text(json.dumps(spec), encoding="utf-8")

    design, _ = load_design_system(ds)
    assert design is not None
    (frontend / "static" / "tokens.css").write_text(
        generate_tokens_css(design), encoding="utf-8"
    )
    (frontend / "templates" / "screens" / "home.html").write_text(
        "<a href=\"{{ url_for('detail') }}\">go</a>", encoding="utf-8"
    )
    (frontend / "templates" / "screens" / "detail.html").write_text(
        "<p>detail</p>", encoding="utf-8"
    )
    return subsystem


# --- generate_tokens_css ---------------------------------------------------------------------


def test_generate_tokens_css_is_sorted_and_deterministic(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    design, _ = load_design_system(ds)
    assert design is not None
    css = generate_tokens_css(design)
    assert css == (
        ":root {\n"
        "  --color-on-surface: #111827;\n"
        "  --color-primary: #1A56DB;\n"
        "  --color-surface: #FFFFFF;\n"
        "  --font-sans: Inter;\n"
        "}\n"
    )


# --- audit_frontend_dir happy path -----------------------------------------------------------


def test_audit_frontend_dir_valid(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert report.is_valid
    assert report.violations == []
    assert report.screens_found == ["detail", "home"]
    assert report.to_dict()["valid"] is True


# --- design system / spec loading failures ---------------------------------------------------


def test_audit_frontend_dir_design_system_missing(tmp_path: Path) -> None:
    report = audit_frontend_dir(tmp_path / "modules" / "cart", design_system_dir=tmp_path / "nope")
    assert not report.is_valid
    assert report.violations


def test_audit_frontend_dir_ui_spec_missing(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = tmp_path / "modules" / "cart"
    subsystem.mkdir(parents=True)
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert not report.is_valid
    assert any("ui-spec.json not found" in v for v in report.violations)


def test_audit_frontend_dir_ui_spec_bad_json(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = tmp_path / "modules" / "cart"
    subsystem.mkdir(parents=True)
    (subsystem / "ui-spec.json").write_text("{not json", encoding="utf-8")
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert not report.is_valid
    assert any("Failed to read or parse" in v for v in report.violations)


def test_audit_frontend_dir_frontend_dir_missing(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = tmp_path / "modules" / "cart"
    subsystem.mkdir(parents=True)
    (subsystem / "ui-spec.json").write_text(json.dumps(_SPEC), encoding="utf-8")
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert not report.is_valid
    assert any("Front-end directory not found" in v for v in report.violations)


# --- _extract_spec_screens branches (via audit_frontend) -------------------------------------


def _design(tmp_path: Path):
    ds = _write_design_system(tmp_path)
    design, _ = load_design_system(ds)
    assert design is not None
    return design


def test_audit_frontend_spec_not_dict(tmp_path: Path) -> None:
    design = _design(tmp_path)
    report = audit_frontend(tmp_path, [], design)
    assert not report.is_valid
    assert any("defines no 'screens'" in v for v in report.violations)


def test_audit_frontend_empty_screens(tmp_path: Path) -> None:
    design = _design(tmp_path)
    report = audit_frontend(tmp_path, {"screens": []}, design)
    assert not report.is_valid
    assert any("defines no 'screens'" in v for v in report.violations)


def test_audit_frontend_skips_malformed_screen_entries(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    design, _ = load_design_system(ds)
    assert design is not None
    frontend = tmp_path / "frontend"
    (frontend / "static").mkdir(parents=True)
    (frontend / "templates" / "screens").mkdir(parents=True)
    (frontend / "static" / "tokens.css").write_text(generate_tokens_css(design), encoding="utf-8")
    (frontend / "templates" / "screens" / "home.html").write_text("<p>home</p>", encoding="utf-8")

    spec = {
        "screens": [
            "not-a-dict",
            {"id": ""},
            {"no": "id"},
            {"id": "home", "transitions": "not-a-list"},
            {"id": "extra", "transitions": [123, {"no": "to"}, {"to": ""}]},
        ]
    }
    report = audit_frontend(frontend, spec, design)
    # 'home' has a template; 'extra' does not -> exactly one missing-template violation.
    assert report.screens_found == ["extra", "home"]
    assert any("Screen 'extra'" in v and "no template" in v for v in report.violations)


# --- token css checks ------------------------------------------------------------------------


def test_tokens_css_missing(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "static" / "tokens.css").unlink()
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("Generated token stylesheet is missing" in v for v in report.violations)


def test_tokens_css_out_of_sync(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "static" / "tokens.css").write_text(
        ":root { --color-primary: #000000; }\n", encoding="utf-8"
    )
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("out of sync" in v for v in report.violations)


# --- magic colors --------------------------------------------------------------------------


def test_magic_color_in_css_detected(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "static" / "app.css").write_text(
        "body { color: var(--color-on-surface); }\n.x { background: #ff0000; }\n",
        encoding="utf-8",
    )
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("raw color literal" in v and "app.css:2" in v for v in report.violations)


def test_clean_css_and_tokens_css_excluded(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    # tokens.css contains hex literals but is excluded; app.css uses only var().
    (subsystem / "frontend" / "static" / "app.css").write_text(
        "body { color: var(--color-primary); }\n", encoding="utf-8"
    )
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert report.is_valid, report.violations


def test_rgb_function_detected(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "static" / "app.css").write_text(
        ".y { color: rgba(0,0,0,0.5); }\n", encoding="utf-8"
    )
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("raw color literal" in v for v in report.violations)


# --- screen bijection + nav wiring ----------------------------------------------------------


def test_missing_screen_template(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "templates" / "screens" / "detail.html").unlink()
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("Screen 'detail'" in v and "no template" in v for v in report.violations)


def test_orphan_template(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "templates" / "screens" / "ghost.html").write_text(
        "<p>ghost</p>", encoding="utf-8"
    )
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("ghost.html" in v and "undeclared screen" in v for v in report.violations)


def test_missing_nav_wiring(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "templates" / "screens" / "home.html").write_text(
        "<p>home with no link</p>", encoding="utf-8"
    )
    report = audit_frontend_dir(subsystem, design_system_dir=ds)
    assert any("transition to 'detail'" in v for v in report.violations)


def test_screens_dir_absent(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    design, _ = load_design_system(ds)
    assert design is not None
    frontend = tmp_path / "frontend"
    (frontend / "static").mkdir(parents=True)
    (frontend / "static" / "tokens.css").write_text(generate_tokens_css(design), encoding="utf-8")
    report = audit_frontend(frontend, _SPEC, design)
    # No templates/screens dir -> both spec screens report as missing templates.
    assert sum("no template" in v for v in report.violations) == 2


# --- main / CLI -----------------------------------------------------------------------------


def test_main_valid_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    rc = main([str(subsystem), "--design-system", str(ds)])
    assert rc == 0
    assert '"valid": true' in capsys.readouterr().out


def test_main_invalid_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ds = _write_design_system(tmp_path)
    subsystem = _build_subsystem(tmp_path, ds)
    (subsystem / "frontend" / "static" / "tokens.css").unlink()
    rc = main([str(subsystem), "--design-system", str(ds)])
    assert rc == 1
    assert "front-end validation failed" in capsys.readouterr().err


def test_main_emit_tokens_css(tmp_path: Path) -> None:
    ds = _write_design_system(tmp_path)
    out = tmp_path / "gen" / "tokens.css"
    rc = main([str(tmp_path), "--design-system", str(ds), "--emit-tokens-css", str(out)])
    assert rc == 0
    design, _ = load_design_system(ds)
    assert design is not None
    assert out.read_text(encoding="utf-8") == generate_tokens_css(design)


def test_main_emit_tokens_css_bad_design_system(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tokens.css"
    rc = main(
        [str(tmp_path), "--design-system", str(tmp_path / "nope"), "--emit-tokens-css", str(out)]
    )
    assert rc == 2
    assert not out.exists()
    assert capsys.readouterr().err
