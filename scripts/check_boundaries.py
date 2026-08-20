"""Directory Boundary Guard for Maestro Subsystem Workers.

Enforces mechanical boundaries by verifying that worker subagents only create or modify
files within their assigned subsystem directories and role-scoped permissions:
- 'test-author': restricted to tests/contract/<subsystem>/ and tests/behavioral/<subsystem>/.
- 'implementer': restricted to src/modules/<subsystem>/, tests/unit/<subsystem>/, and
  tests/integration/<subsystem>/.
- Unset / 'any': allows all four subsystem prefixes (backward-compatible default).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BoundaryResult:
    """Result of a boundary check evaluation."""

    is_valid: bool
    target_path: str
    subsystem: str
    role: str | None = None
    violation: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        """Convert result to serializable dictionary."""
        d = asdict(self)
        d["valid"] = self.is_valid
        return d


def _get_allowed_prefixes(subsystem: str, role: str | None = None) -> list[str]:
    """Generate normalized allowed path prefixes for a given subsystem and role.

    Args:
        subsystem: Clean subsystem identifier.
        role: Optional active persona role ('test-author', 'implementer', 'any', or None).

    Returns:
        List of permitted path prefixes. Empty list indicates fail-closed rejection.
    """
    clean_role = role.strip().lower() if role and role.strip() else None

    if clean_role == "test-author":
        return [
            f"tests/contract/{subsystem}",
            f"tests/behavioral/{subsystem}",
        ]

    if clean_role == "implementer":
        # NOTE: Unit tests stay with the implementer to preserve the tight TDD loop;
        # orthogonal contract/behavioral tests are protected from implementer mutation.
        return [
            f"src/modules/{subsystem}",
            f"tests/unit/{subsystem}",
            f"tests/integration/{subsystem}",
        ]

    if clean_role in (None, "any"):
        return [
            f"src/modules/{subsystem}",
            f"tests/unit/{subsystem}",
            f"tests/integration/{subsystem}",
            f"tests/contract/{subsystem}",
            f"tests/behavioral/{subsystem}",
            f"tests/{subsystem}",
        ]

    # Unknown role: fail-closed with empty list
    return []


def check_boundary(
    subsystem: str,
    target_path: str,
    role: str | None = None,
    repo_root: str | Path | None = None,
) -> BoundaryResult:
    """Evaluate whether a target file path is within the allowed subsystem boundary and role.

    Args:
        subsystem: Name of the assigned subsystem (e.g., 'billing').
        target_path: Relative or absolute path to the target file.
        role: Optional persona role ('test-author', 'implementer', etc.).
        repo_root: Base repository directory. Defaults to current working directory.

    Returns:
        BoundaryResult indicating whether the path is permitted.

    Raises:
        ValueError: If subsystem name is empty or whitespace.
    """
    if not subsystem or not subsystem.strip():
        raise ValueError("Subsystem name cannot be empty.")

    clean_subsystem = subsystem.strip()
    active_role = role or os.environ.get("MAESTRO_ACTIVE_ROLE", "").strip() or None
    root_path = Path(repo_root or os.getcwd()).resolve()

    # Normalize target path
    raw_path = Path(target_path)
    if raw_path.is_absolute():
        try:
            rel_path = raw_path.resolve().relative_to(root_path)
        except ValueError:
            return BoundaryResult(
                is_valid=False,
                target_path=target_path,
                subsystem=clean_subsystem,
                role=active_role,
                violation=(f"Path '{target_path}' is outside repository root '{root_path}'."),
            )
    else:
        # Resolve path relative to repo_root
        combined = (root_path / raw_path).resolve()
        try:
            rel_path = combined.relative_to(root_path)
        except ValueError:
            return BoundaryResult(
                is_valid=False,
                target_path=target_path,
                subsystem=clean_subsystem,
                role=active_role,
                violation=(
                    f"Path '{target_path}' attempts directory traversal outside repository root."
                ),
            )

    rel_posix = rel_path.as_posix()
    allowed_prefixes = _get_allowed_prefixes(clean_subsystem, role=active_role)

    if active_role is not None and not allowed_prefixes:
        return BoundaryResult(
            is_valid=False,
            target_path=rel_posix,
            subsystem=clean_subsystem,
            role=active_role,
            violation=(
                f"Unknown or unauthorized role '{active_role}'. No write paths are permitted."
            ),
        )

    is_allowed = any(
        rel_posix == prefix or rel_posix.startswith(f"{prefix}/") for prefix in allowed_prefixes
    )

    if is_allowed:
        return BoundaryResult(
            is_valid=True,
            target_path=rel_posix,
            subsystem=clean_subsystem,
            role=active_role,
        )

    role_desc = f"role '{active_role}'" if active_role else "default role"
    allowed_desc = ", ".join(allowed_prefixes) if allowed_prefixes else "none"
    return BoundaryResult(
        is_valid=False,
        target_path=rel_posix,
        subsystem=clean_subsystem,
        role=active_role,
        violation=(
            f"Path '{rel_posix}' is outside assigned subsystem boundary for '{clean_subsystem}' "
            f"with {role_desc}. Allowed locations: {allowed_desc}."
        ),
    )


def check_paths_boundary(
    subsystem: str,
    target_paths: Sequence[str],
    role: str | None = None,
    repo_root: str | Path | None = None,
) -> list[BoundaryResult]:
    """Evaluate a batch of target paths against the subsystem boundary and role.

    Args:
        subsystem: Name of the assigned subsystem.
        target_paths: Sequence of file paths to check.
        role: Optional persona role.
        repo_root: Base repository directory.

    Returns:
        List of BoundaryResult objects.
    """
    return [check_boundary(subsystem, p, role=role, repo_root=repo_root) for p in target_paths]


def check_tool_input(
    subsystem: str,
    tool_input_json: str,
    role: str | None = None,
    repo_root: str | Path | None = None,
) -> BoundaryResult:
    """Extract and validate target file from a tool input JSON payload (e.g. PreToolUse hook).

    Recognized keys: 'TargetFile', 'AbsolutePath', 'file_path', 'path', 'target_path'.

    Args:
        subsystem: Name of the assigned subsystem.
        tool_input_json: JSON string payload from tool invocation.
        role: Optional persona role.
        repo_root: Base repository directory.

    Returns:
        BoundaryResult indicating validation outcome.
    """
    try:
        data = json.loads(tool_input_json)
    except json.JSONDecodeError as err:
        return BoundaryResult(
            is_valid=False,
            target_path="",
            subsystem=subsystem,
            role=role,
            violation=f"Invalid JSON in tool input: {err}",
        )

    if not isinstance(data, dict):
        return BoundaryResult(
            is_valid=True,
            target_path="",
            subsystem=subsystem,
            role=role,
        )

    candidate_keys = ["TargetFile", "AbsolutePath", "file_path", "path", "target_path"]
    for key in candidate_keys:
        if key in data and isinstance(data[key], str):
            return check_boundary(subsystem, data[key], role=role, repo_root=repo_root)

    # If tool payload contains no recognized file path (e.g., bash command), allow gracefully
    return BoundaryResult(
        is_valid=True,
        target_path="",
        subsystem=subsystem,
        role=role,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for boundary checks."""
    parser = argparse.ArgumentParser(
        description="Verify that file paths reside strictly within assigned subsystem boundaries."
    )
    parser.add_argument(
        "--subsystem",
        "-s",
        required=True,
        help="Assigned subsystem name (e.g., 'billing').",
    )
    parser.add_argument(
        "--role",
        "-R",
        help="Active persona role ('test-author', 'implementer', or unset/any).",
    )
    parser.add_argument(
        "--path",
        "-p",
        help="Single file path to validate.",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        help="Multiple file paths to validate.",
    )
    parser.add_argument(
        "--tool-input",
        "-t",
        help="Raw JSON payload from tool call / PreToolUse hook.",
    )
    parser.add_argument(
        "--root",
        "-r",
        help="Repository root directory. Defaults to current directory.",
    )

    args = parser.parse_args(argv)

    if args.tool_input:
        res = check_tool_input(args.subsystem, args.tool_input, role=args.role, repo_root=args.root)
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.is_valid else 1

    targets: list[str] = []
    if args.path:
        targets.append(args.path)
    if args.paths:
        targets.extend(args.paths)

    if not targets:
        print(
            json.dumps(
                {"valid": False, "error": "Must provide --path, --paths, or --tool-input"}, indent=2
            ),
            file=sys.stderr,
        )
        return 2

    results = check_paths_boundary(args.subsystem, targets, role=args.role, repo_root=args.root)
    all_valid = all(r.is_valid for r in results)

    output: dict[str, Any] = {
        "valid": all_valid,
        "subsystem": args.subsystem,
        "role": args.role,
        "results": [r.to_dict() for r in results],
    }
    if not all_valid:
        violations = [r.violation for r in results if not r.is_valid]
        output["violation"] = "; ".join(filter(None, violations))

    print(json.dumps(output, indent=2))
    return 0 if all_valid else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
