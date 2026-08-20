"""Specialist Implementer Auditor (Gate 2 mechanical enforcement).

Statically audits a subsystem's implementation tree (``src/modules/<subsystem>/``) against the
non-negotiable structural invariants of the Specialist Implementer (``/code-implement``) persona,
so those invariants cannot silently drift under task pressure:

* **One public class per file.** Behavioural components (rules, stages, states, solvers, ports,
  adapters, engines) each live in a dedicated file. Only explicit collection modules
  (``models.py``, ``exceptions.py``) may declare multiple public classes.
* **Domain layer purity.** Files under ``domain/`` never import external I/O libraries
  (databases, HTTP clients, cloud SDKs, web frameworks) and never import the subsystem's own
  ``adapters``/``entrypoints`` packages. The dependency arrow points inward: adapters depend on
  domain ports, never the reverse.
* **Docstring presence.** Every non-package module, every public class, and every public
  function/method carries a docstring.

This complements ``scripts/check_boundaries.py`` (which proves *where* files may be written) by
proving the files that were written obey the clean-architecture contract.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Modules explicitly permitted to declare more than one public class (value-object / error
# collections). Every other module is held to the one-public-class-per-file invariant.
MULTI_CLASS_ALLOWED: frozenset[str] = frozenset({"models.py", "exceptions.py"})

# Import prefixes that constitute external I/O and therefore must never appear in ``domain/``.
# A blocklist (rather than a stdlib allowlist) mirrors the isolation check in
# ``audit_test_coverage.py`` and stays robust as pure stdlib usage evolves.
IO_IMPORT_PREFIXES: tuple[str, ...] = (
    "google",
    "googleapiclient",
    "firebase_admin",
    "httpx",
    "requests",
    "urllib.request",
    "urllib3",
    "aiohttp",
    "sqlalchemy",
    "psycopg2",
    "psycopg",
    "pymongo",
    "redis",
    "boto3",
    "fastapi",
    "starlette",
    "flask",
    "django",
    "socket",
    "sqlite3",
    "http.client",
    "smtplib",
    "ftplib",
    "kafka",
    "pika",
)

# Sibling layers the domain must never depend on (dependency inversion).
FORBIDDEN_DOMAIN_LAYERS: tuple[str, ...] = ("adapters", "entrypoints")


@dataclass(frozen=True)
class ImplementationAuditReport:
    """Report of structural invariant violations across a subsystem implementation tree."""

    is_valid: bool
    subsystem: str
    files_checked: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def _import_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the fully-qualified module paths introduced by an import node.

    For ``import a.b, c`` this yields ``["a.b", "c"]``; for ``from a.b import x`` it yields
    ``["a.b"]``. Relative imports (``from . import x``) yield their ``module`` part only, which is
    sufficient for detecting forbidden sibling-layer segments.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return [node.module] if node.module else []


def _is_io_import(module: str) -> bool:
    """Return True if ``module`` matches (equals or is under) a blocklisted I/O prefix."""
    return any(module == p or module.startswith(f"{p}.") for p in IO_IMPORT_PREFIXES)


def _forbidden_layer(node: ast.Import | ast.ImportFrom) -> str | None:
    """Return the sibling layer name if this import reaches into ``adapters``/``entrypoints``."""
    segments: list[str] = []
    for module in _import_roots(node):
        segments.extend(module.split("."))
    # Relative imports carry their leading package in ``module`` only when present; the segment
    # scan above already covers ``from ..adapters.foo import x`` (module="adapters.foo").
    for layer in FORBIDDEN_DOMAIN_LAYERS:
        if layer in segments:
            return layer
    return None


def _check_docstrings(tree: ast.Module, label: str, *, is_package: bool) -> list[str]:
    """Return docstring-presence violations for a parsed module."""
    violations: list[str] = []
    if not is_package and ast.get_docstring(tree) is None:
        violations.append(f"{label}: module is missing a docstring.")

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            kind = "function"
        else:
            continue
        if node.name.startswith("_") or ast.get_docstring(node) is not None:
            continue
        violations.append(f"{label}: public {kind} '{node.name}' is missing a docstring.")
    return violations


def analyze_source(
    source: str,
    *,
    label: str,
    is_domain: bool,
    is_package: bool,
    check_single_class: bool,
) -> list[str]:
    """Audit a single Python source file's text against the structural invariants.

    Args:
        source: Raw Python source code.
        label: Human-readable file label used in violation messages.
        is_domain: Whether the file lives under the subsystem's ``domain/`` layer.
        is_package: Whether the file is a package marker (``__init__.py``).
        check_single_class: Whether the one-public-class-per-file rule applies to this file.

    Returns:
        A list of violation messages (empty if the file is compliant).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as err:
        return [f"{label}: could not parse Python source ({err.msg})."]

    violations: list[str] = []

    if check_single_class:
        public_classes = [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        ]
        if len(public_classes) > 1:
            violations.append(
                f"{label}: declares {len(public_classes)} public classes "
                f"({', '.join(public_classes)}); enforce one public class per file."
            )

    if is_domain:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            for module in _import_roots(node):
                if _is_io_import(module):
                    violations.append(
                        f"{label}: domain layer imports external I/O module '{module}'; "
                        "move I/O behind an abc.ABC port implemented in adapters/."
                    )
            layer = _forbidden_layer(node)
            if layer is not None:
                violations.append(
                    f"{label}: domain layer imports the subsystem's '{layer}' package; "
                    "domain must not depend on adapters/entrypoints (dependency inversion)."
                )

    violations.extend(_check_docstrings(tree, label, is_package=is_package))
    return violations


def audit_subsystem_dir(subsystem_dir: str | Path) -> ImplementationAuditReport:
    """Walk a subsystem directory and audit every Python file it contains.

    Args:
        subsystem_dir: Path to ``src/modules/<subsystem>/``.

    Returns:
        An ImplementationAuditReport aggregating violations across the tree.
    """
    root = Path(subsystem_dir)
    subsystem = root.resolve().name

    if not root.is_dir():
        return ImplementationAuditReport(
            is_valid=False,
            subsystem=subsystem,
            violations=[f"Subsystem directory not found: '{root}'."],
        )

    py_files = sorted(root.rglob("*.py"))
    files_checked: list[str] = []
    violations: list[str] = []

    for path in py_files:
        rel = path.relative_to(root)
        label = rel.as_posix()
        files_checked.append(label)
        is_package = path.name == "__init__.py"
        is_domain = bool(rel.parts) and rel.parts[0] == "domain"
        check_single_class = not is_package and path.name not in MULTI_CLASS_ALLOWED
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as err:  # pragma: no cover - defensive I/O guard
            violations.append(f"{label}: failed to read file ({err}).")
            continue
        violations.extend(
            analyze_source(
                source,
                label=label,
                is_domain=is_domain,
                is_package=is_package,
                check_single_class=check_single_class,
            )
        )

    if not py_files:
        violations.append(f"Subsystem '{subsystem}' contains no Python source files.")

    return ImplementationAuditReport(
        is_valid=len(violations) == 0,
        subsystem=subsystem,
        files_checked=files_checked,
        violations=violations,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the Gate 2 implementation audit."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit a subsystem implementation tree for one-class-per-file, domain purity, "
            "and docstring presence."
        )
    )
    parser.add_argument(
        "subsystem_dir",
        help="Path to the subsystem directory (e.g., src/modules/redirect_resolver).",
    )

    args = parser.parse_args(argv)

    report = audit_subsystem_dir(args.subsystem_dir)
    print(json.dumps(report.to_dict(), indent=2))

    if not report.is_valid:
        print(
            f"ERROR: Implementation audit failed with {len(report.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in report.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
