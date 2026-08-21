"""Unit tests for scripts/import_claude_design.py."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.import_claude_design import (
    ImportReport,
    _extract_colors,
    _extract_components,
    _extract_fonts,
    _first_family,
    _font_token_families,
    _normalize_hex,
    _read_zip_text_entries,
    _reverse_color_map,
    build_draft_ui_spec,
    build_import_report,
    import_export_file,
    main,
)
from scripts.validate_ui_spec import DesignSystem


def _design() -> DesignSystem:
    return DesignSystem(
        tokens={
            "color": {"brand": "#1A56DB", "surface": "#FFF", "bad": "notahex"},
            "font": {"sans": "Inter, sans-serif", "trailing": "Roboto,"},
        },
        components=frozenset({"Button", "Card"}),
        contrast_normal=4.5,
        contrast_large=3.0,
    )


def _make_zip(path: Path, files: dict[str, str], *, add_dir: bool = False) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if add_dir:
            archive.writestr(zipfile.ZipInfo("assets/"), "")
        for name, content in files.items():
            archive.writestr(name, content)
    return path


# --------------------------------------------------------------------------- primitives


def test_normalize_hex_variants() -> None:
    assert _normalize_hex("#FFF") == "#ffffff"
    assert _normalize_hex("#1A56DB") == "#1a56db"
    assert _normalize_hex("#1a56db80") == "#1a56db"  # 8-digit (alpha) truncated
    assert _normalize_hex("#abcd") is None  # 4-digit is not supported


def test_first_family() -> None:
    assert _first_family("'Inter', sans-serif") == "Inter"
    assert _first_family("  Roboto  ") == "Roboto"


def test_extract_colors_skips_invalid() -> None:
    colors = _extract_colors("a{color:#1A56DB} b{color:#abcd} c{color:#fff}")
    assert colors == {"#1a56db", "#ffffff"}


def test_extract_fonts_skips_empty() -> None:
    text = "a{font-family: Inter, sans-serif} b{font-family: ;} c{fontFamily:'Ubuntu'}"
    assert _extract_fonts(text) == {"Inter", "Ubuntu"}


def test_extract_components() -> None:
    assert _extract_components("<Button><Card/><div><IconButton>") == {
        "Button",
        "Card",
        "IconButton",
    }


def test_reverse_color_map_skips_bad_token() -> None:
    reverse = _reverse_color_map(_design())
    assert reverse["#1a56db"] == "{color.brand}"
    assert reverse["#ffffff"] == "{color.surface}"
    assert all("notahex" not in k for k in reverse)  # bad hex token dropped


def test_font_token_families_skips_empty_part() -> None:
    families = _font_token_families(_design())
    assert families["inter"] == "{font.sans}"
    assert families["sans-serif"] == "{font.sans}"
    assert families["roboto"] == "{font.trailing}"  # trailing comma part skipped, no crash


# --------------------------------------------------------------------------- zip reading


def test_read_zip_missing_file(tmp_path: Path) -> None:
    entries, violations = _read_zip_text_entries(tmp_path / "nope.zip")
    assert entries is None
    assert "not found" in violations[0]


def test_read_zip_corrupt(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"this is not a zip file")
    entries, violations = _read_zip_text_entries(bad)
    assert entries is None
    assert "Failed to read" in violations[0]


def test_read_zip_no_importable_files(tmp_path: Path) -> None:
    zip_path = _make_zip(tmp_path / "assets.zip", {"logo.png": "binary-ish"})
    entries, violations = _read_zip_text_entries(zip_path)
    assert entries is None
    assert "no importable text files" in violations[0]


def test_read_zip_success_skips_dirs_and_binaries(tmp_path: Path) -> None:
    zip_path = _make_zip(
        tmp_path / "export.zip",
        {"App.jsx": "<Button/>", "styles.css": ".a{}", "logo.png": "x"},
        add_dir=True,
    )
    entries, violations = _read_zip_text_entries(zip_path)
    assert violations == []
    assert entries is not None
    names = sorted(name for name, _ in entries)
    assert names == ["App.jsx", "styles.css"]  # dir + png excluded


# --------------------------------------------------------------------------- report


def test_build_import_report_maps_and_flags() -> None:
    entries = [
        ("styles.css", ".a{color:#1A56DB;background:#123456;font-family: Inter, sans-serif;}"),
        ("App.jsx", "<Button/><Widget/>\nfontFamily: 'Comic Sans'"),
    ]
    report = build_import_report(entries, _design(), zip_path="export.zip")
    assert report.zip_path == "export.zip"
    assert report.files_scanned == ["App.jsx", "styles.css"]
    assert report.mapped_colors == {"#1a56db": "{color.brand}"}
    assert report.unmapped_colors == ["#123456"]
    assert report.mapped_fonts == {"Inter": "{font.sans}"}
    assert report.unmapped_fonts == ["Comic Sans"]
    assert report.whitelisted_components == ["Button"]
    assert report.non_whitelisted_components == ["Widget"]


# --------------------------------------------------------------------------- draft


def test_build_draft_ui_spec_with_findings() -> None:
    report = ImportReport(
        zip_path="e.zip",
        unmapped_colors=["#123456"],
        unmapped_fonts=["Comic Sans"],
        whitelisted_components=["Button"],
        non_whitelisted_components=["Widget"],
    )
    draft = build_draft_ui_spec(report)
    assert draft["schema"] == "maestro/ui-spec@1"
    assert draft["screens"][0]["components"] == ["Button"]
    notes = draft["_draft_notes"]
    assert any("#123456" in n for n in notes)
    assert any("Comic Sans" in n for n in notes)
    assert any("Widget" in n for n in notes)


def test_build_draft_ui_spec_clean_report() -> None:
    draft = build_draft_ui_spec(ImportReport(zip_path="e.zip"))
    # Only the mandatory "complete it" note when nothing is off-brand.
    assert len(draft["_draft_notes"]) == 1
    assert draft["screens"][0]["components"] == []


# --------------------------------------------------------------------------- file-level


def test_import_export_file_bad_design_system(tmp_path: Path) -> None:
    zip_path = _make_zip(tmp_path / "export.zip", {"App.jsx": "<Button/>"})
    report = import_export_file(zip_path, design_system_dir=tmp_path / "missing-ds")
    assert report.violations  # design system could not be loaded
    assert report.files_scanned == []


def test_import_export_file_bad_archive(tmp_path: Path) -> None:
    report = import_export_file(tmp_path / "nope.zip")
    assert report.violations
    assert "not found" in report.violations[0]


def test_import_export_file_success_with_draft(tmp_path: Path) -> None:
    zip_path = _make_zip(
        tmp_path / "export.zip",
        {"App.jsx": "<Button/><Widget/>", "s.css": ".a{color:#1A56DB;background:#FFFFFF}"},
    )
    draft_path = tmp_path / "ui-spec.draft.json"
    report = import_export_file(zip_path, emit_draft_path=draft_path)
    assert report.violations == []
    assert report.mapped_colors["#1a56db"] == "{color.brand-primary}"
    assert "#ffffff" in report.mapped_colors  # maps to a shipped white token
    assert draft_path.is_file()
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["screens"][0]["components"] == ["Button"]


def test_import_export_file_success_no_draft(tmp_path: Path) -> None:
    zip_path = _make_zip(tmp_path / "export.zip", {"App.jsx": "<Card/>"})
    report = import_export_file(zip_path)
    assert report.violations == []
    assert report.whitelisted_components == ["Card"]


# --------------------------------------------------------------------------- CLI


def test_main_success(tmp_path: Path, capsys: object) -> None:
    zip_path = _make_zip(tmp_path / "export.zip", {"App.jsx": "<Button/>"})
    exit_code = main([str(zip_path)])
    assert exit_code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Scanned 1 file" in captured.err


def test_main_success_with_draft(tmp_path: Path, capsys: object) -> None:
    zip_path = _make_zip(tmp_path / "export.zip", {"App.jsx": "<Button/>"})
    draft_path = tmp_path / "draft.json"
    exit_code = main([str(zip_path), "--emit-draft", str(draft_path)])
    assert exit_code == 0
    assert draft_path.is_file()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Wrote draft ui-spec scaffold" in captured.err


def test_main_failure(tmp_path: Path, capsys: object) -> None:
    exit_code = main([str(tmp_path / "nope.zip")])
    assert exit_code == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "import failed" in captured.err
