"""Unit tests for the Specialist Implementer Auditor (scripts/audit_implementation.py)."""

import json
from pathlib import Path

import pytest

from scripts.audit_implementation import (
    ImplementationAuditReport,
    analyze_source,
    audit_subsystem_dir,
    main,
)

CLEAN_RULE = '''"""A clean rule module."""

import abc


class ValidateUrlRule(abc.ABC):
    """A rule port."""

    @abc.abstractmethod
    def apply(self, value: str) -> bool:
        """Apply the rule."""
'''

MODELS = '''"""Domain models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortLink:
    """A short link."""

    code: str


@dataclass(frozen=True)
class Target:
    """A resolution target."""

    url: str
'''

ADAPTER = '''"""In-memory adapter."""


class InMemoryRepo:
    """An in-memory repository."""

    def get(self, code: str) -> str:
        """Return the code."""
        return code
'''


def test_clean_domain_file_passes() -> None:
    """Verify a compliant domain file yields no violations."""
    result = analyze_source(
        CLEAN_RULE,
        label="domain/rules/validate_url.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert result == []


def test_multiple_public_classes_flagged() -> None:
    """Verify two public classes in a non-collection file is a violation."""
    source = '"""Mod."""\n\n\nclass A:\n    """A."""\n\n\nclass B:\n    """B."""\n'
    result = analyze_source(
        source,
        label="domain/thing.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert any("one public class per file" in v for v in result)


def test_collection_module_allows_multiple_classes() -> None:
    """Verify allowlisted collection modules may declare multiple public classes."""
    result = analyze_source(
        MODELS,
        label="domain/models.py",
        is_domain=True,
        is_package=False,
        check_single_class=False,
    )
    assert result == []


def test_missing_module_docstring_flagged() -> None:
    """Verify a non-package module without a docstring is flagged."""
    source = 'class A:\n    """A."""\n'
    result = analyze_source(
        source,
        label="domain/a.py",
        is_domain=False,
        is_package=False,
        check_single_class=True,
    )
    assert any("module is missing a docstring" in v for v in result)


def test_package_module_skips_docstring_requirement() -> None:
    """Verify a package marker (__init__.py) is exempt from the module docstring rule."""
    result = analyze_source(
        "",
        label="domain/__init__.py",
        is_domain=True,
        is_package=True,
        check_single_class=False,
    )
    assert result == []


def test_class_missing_docstring_flagged() -> None:
    """Verify a public class without a docstring is flagged."""
    source = '"""Mod."""\n\n\nclass A:\n    pass\n'
    result = analyze_source(
        source,
        label="domain/a.py",
        is_domain=False,
        is_package=False,
        check_single_class=True,
    )
    assert any("public class 'A' is missing a docstring" in v for v in result)


def test_function_missing_docstring_flagged() -> None:
    """Verify a public function without a docstring is flagged."""
    source = '"""Mod."""\n\n\ndef do_thing() -> None:\n    return None\n'
    result = analyze_source(
        source,
        label="domain/a.py",
        is_domain=False,
        is_package=False,
        check_single_class=True,
    )
    assert any("public function 'do_thing' is missing a docstring" in v for v in result)


def test_async_function_missing_docstring_flagged() -> None:
    """Verify a public async function without a docstring is flagged."""
    source = '"""Mod."""\n\n\nasync def fetch() -> None:\n    return None\n'
    result = analyze_source(
        source,
        label="adapters/a.py",
        is_domain=False,
        is_package=False,
        check_single_class=True,
    )
    assert any("public function 'fetch' is missing a docstring" in v for v in result)


def test_private_members_exempt_from_docstrings() -> None:
    """Verify underscore-prefixed classes and functions do not require docstrings."""
    source = (
        '"""Mod."""\n\n\ndef _helper() -> None:\n    return None\n\n\nclass _Internal:\n    pass\n'
    )
    result = analyze_source(
        source,
        label="domain/a.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert result == []


def test_domain_io_import_flagged() -> None:
    """Verify a domain file importing an external I/O SDK is flagged."""
    source = '"""Mod."""\n\nimport google.cloud.firestore\n'
    result = analyze_source(
        source,
        label="domain/repo.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert any("external I/O module 'google.cloud.firestore'" in v for v in result)


def test_domain_from_io_import_flagged() -> None:
    """Verify a domain file importing an HTTP client via from-import is flagged."""
    source = '"""Mod."""\n\nfrom httpx import Client\n'
    result = analyze_source(
        source,
        label="domain/client.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert any("external I/O module 'httpx'" in v for v in result)


def test_domain_importing_sibling_layer_flagged() -> None:
    """Verify a domain file importing the subsystem's adapters package is flagged."""
    source = '"""Mod."""\n\nfrom ..adapters.repo import Repo\n'
    result = analyze_source(
        source,
        label="domain/service.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert any("imports the subsystem's 'adapters' package" in v for v in result)


def test_domain_relative_sibling_import_is_benign() -> None:
    """Verify an intra-domain relative import (module=None) raises no violation."""
    source = '"""Mod."""\n\nfrom . import base\n'
    result = analyze_source(
        source,
        label="domain/engine.py",
        is_domain=True,
        is_package=False,
        check_single_class=False,
    )
    assert result == []


def test_io_import_ignored_outside_domain() -> None:
    """Verify I/O imports are permitted outside the domain layer (e.g. adapters)."""
    source = '"""Mod."""\n\nimport google.cloud.firestore\n'
    result = analyze_source(
        source,
        label="adapters/firestore_repo.py",
        is_domain=False,
        is_package=False,
        check_single_class=True,
    )
    assert result == []


def test_syntax_error_flagged() -> None:
    """Verify an unparseable file is reported rather than crashing."""
    result = analyze_source(
        "def broken(",
        label="domain/broken.py",
        is_domain=True,
        is_package=False,
        check_single_class=True,
    )
    assert any("could not parse Python source" in v for v in result)


def _scaffold_valid(tmp_path: Path) -> Path:
    """Create a compliant subsystem tree and return its directory."""
    root = tmp_path / "src" / "modules" / "redirect_resolver"
    (root / "domain" / "rules").mkdir(parents=True)
    (root / "adapters").mkdir()
    (root / "entrypoints").mkdir()

    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (root / "domain" / "rules" / "__init__.py").write_text("", encoding="utf-8")
    (root / "domain" / "models.py").write_text(MODELS, encoding="utf-8")
    (root / "domain" / "rules" / "validate_url.py").write_text(CLEAN_RULE, encoding="utf-8")
    (root / "adapters" / "__init__.py").write_text("", encoding="utf-8")
    (root / "adapters" / "in_memory_repo.py").write_text(ADAPTER, encoding="utf-8")
    (root / "entrypoints" / "__init__.py").write_text("", encoding="utf-8")
    return root


def test_audit_subsystem_dir_valid(tmp_path: Path) -> None:
    """Verify a fully compliant subsystem tree passes."""
    root = _scaffold_valid(tmp_path)
    report = audit_subsystem_dir(root)
    assert report.is_valid is True
    assert report.subsystem == "redirect_resolver"
    assert "domain/rules/validate_url.py" in report.files_checked


def test_audit_subsystem_dir_aggregates_violations(tmp_path: Path) -> None:
    """Verify violations from an individual file surface in the aggregate report."""
    root = _scaffold_valid(tmp_path)
    bad = '"""Mod."""\n\n\nclass A:\n    """A."""\n\n\nclass B:\n    """B."""\n'
    (root / "domain" / "two_classes.py").write_text(bad, encoding="utf-8")
    report = audit_subsystem_dir(root)
    assert report.is_valid is False
    assert any("two_classes.py" in v for v in report.violations)


def test_audit_subsystem_dir_missing(tmp_path: Path) -> None:
    """Verify a nonexistent subsystem directory is reported."""
    report = audit_subsystem_dir(tmp_path / "nope")
    assert report.is_valid is False
    assert any("not found" in v for v in report.violations)


def test_audit_subsystem_dir_empty(tmp_path: Path) -> None:
    """Verify a directory with no Python files is flagged."""
    root = tmp_path / "src" / "modules" / "empty_sub"
    root.mkdir(parents=True)
    report = audit_subsystem_dir(root)
    assert report.is_valid is False
    assert any("no Python source files" in v for v in report.violations)


def test_to_dict_exposes_valid_alias(tmp_path: Path) -> None:
    """Verify ImplementationAuditReport.to_dict exposes the 'valid' alias."""
    report = audit_subsystem_dir(_scaffold_valid(tmp_path))
    data = report.to_dict()
    assert data["valid"] is True
    assert isinstance(report, ImplementationAuditReport)


def test_main_cli_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify the CLI exits 0 and reports valid on a compliant tree."""
    root = _scaffold_valid(tmp_path)
    exit_code = main([str(root)])
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["valid"] is True


def test_main_cli_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify the CLI exits 1 and prints diagnostics on violations."""
    exit_code = main([str(tmp_path / "nope")])
    assert exit_code == 1
    assert "Implementation audit failed" in capsys.readouterr().err


def test_main_cli_missing_arg() -> None:
    """Verify the CLI errors when the subsystem argument is omitted."""
    with pytest.raises(SystemExit):
        main([])
