"""Harness PreToolUse Hook Adapter for Directory Boundary Guard.

Intercepts tool executions (such as write_to_file and replace_file_content) in real time
before they execute in the harness runtime. Reads tool call payload from stdin,
evaluates subsystem isolation against MAESTRO_ACTIVE_SUBSYSTEM and MAESTRO_ACTIVE_ROLE,
and outputs an unbypassable allow/deny decision JSON on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

# The Antigravity harness invokes this file directly as
# `python3 scripts/hook_boundary_guard.py`, which puts scripts/ (not the repo
# root) on sys.path and makes `import scripts.check_boundaries` fail. Add the
# repo root so the shared module resolves both on direct invocation and under
# pytest (which already has the repo root on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_boundaries import check_boundary  # noqa: E402


def process_pre_tool_use_hook(
    stdin_data: str,
    subsystem_override: str | None = None,
    role_override: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, str]:
    """Process a PreToolUse hook payload and decide allow vs deny.

    Args:
        stdin_data: JSON string passed via stdin by the agent harness.
        subsystem_override: Optional subsystem name overriding environment variable.
        role_override: Optional persona role overriding environment variable.
        repo_root: Optional repository root path.

    Returns:
        Dictionary with 'decision' ('allow' or 'deny') and optional 'reason'.
    """
    subsystem = subsystem_override or os.environ.get("MAESTRO_ACTIVE_SUBSYSTEM", "").strip()
    role = role_override or os.environ.get("MAESTRO_ACTIVE_ROLE", "").strip() or None

    # If no subsystem constraint is active (e.g. Architect or Conductor at root), allow
    if not subsystem:
        return {"decision": "allow"}

    if not stdin_data or not stdin_data.strip():
        return {"decision": "allow"}

    try:
        payload = json.loads(stdin_data)
    except json.JSONDecodeError:
        # Malformed hook payload should not crash harness, but allow standard processing
        return {"decision": "allow"}

    if not isinstance(payload, dict):
        return {"decision": "allow"}

    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}

    args = tool_call.get("args")
    if not isinstance(args, dict):
        return {"decision": "allow"}

    candidate_keys = ["TargetFile", "AbsolutePath", "file_path", "path", "target_path", "file"]
    target_path: str | None = None
    for key in candidate_keys:
        if key in args and isinstance(args[key], str):
            target_path = args[key]
            break

    if not target_path:
        return {"decision": "allow"}

    res = check_boundary(subsystem, target_path, role=role, repo_root=repo_root)
    if res.is_valid:
        return {"decision": "allow"}

    return {
        "decision": "deny",
        "reason": f"PreToolUse Boundary Guard: {res.violation}",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the PreToolUse hook."""
    parser = argparse.ArgumentParser(
        description="PreToolUse hook adapter enforcing mechanical subsystem boundaries."
    )
    parser.add_argument(
        "--subsystem",
        "-s",
        help="Explicit subsystem constraint (overrides MAESTRO_ACTIVE_SUBSYSTEM env var).",
    )
    parser.add_argument(
        "--role",
        "-R",
        help="Explicit persona role (overrides MAESTRO_ACTIVE_ROLE env var).",
    )
    parser.add_argument(
        "--root",
        "-r",
        help="Repository root directory.",
    )

    args = parser.parse_args(argv)

    try:
        stdin_content = sys.stdin.read()
    except Exception:  # pragma: no cover
        stdin_content = ""

    result = process_pre_tool_use_hook(
        stdin_content,
        subsystem_override=args.subsystem,
        role_override=args.role,
        repo_root=args.root,
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
