"""Mechanical RED-Lock Validator for Orthogonal Test Suites.

Enforces mechanical test isolation between Test Architect and Implementer:
1. `lock`: Verifies orthogonal test suite exists, is genuinely failing (RED),
   and captures SHA256 hashes of all locked test files into .maestro/red_lock/<sub>.json.
2. `check`: Verifies the locked test suite has not been tampered with (added, modified,
   or deleted) during implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = ".maestro/red_lock"


def _hash_file(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    hasher = hashlib.sha256()
    hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def _collect_orthogonal_test_files(
    subsystem: str,
    repo_root: Path,
) -> list[Path]:
    """Collect all test_*.py files in tests/contract/<sub> and tests/behavioral/<sub>."""
    target_dirs = [
        repo_root / "tests" / "contract" / subsystem,
        repo_root / "tests" / "behavioral" / subsystem,
    ]
    files: list[Path] = []
    for d in target_dirs:
        if d.is_dir():
            for p in sorted(d.rglob("test_*.py")):
                if p.is_file():
                    files.append(p)
    return files


def lock_red_suite(
    subsystem: str,
    state_dir: str | Path = DEFAULT_STATE_DIR,
    repo_root: str | Path | None = None,
    pytest_runner: Sequence[str] = ("pytest",),
) -> tuple[int, dict[str, Any]]:
    """Lock the orthogonal test suite after verifying it is genuinely RED."""
    root = Path(repo_root or Path.cwd()).resolve()
    clean_subsystem = subsystem.strip()

    contract_dir = root / "tests" / "contract" / clean_subsystem
    behavioral_dir = root / "tests" / "behavioral" / clean_subsystem

    # Check directories and file presence
    test_files = _collect_orthogonal_test_files(clean_subsystem, root)
    if not test_files:
        return 1, {
            "valid": False,
            "subsystem": clean_subsystem,
            "error": (
                f"No orthogonal test files found in '{contract_dir.relative_to(root)}' or "
                f"'{behavioral_dir.relative_to(root)}'. Author contract/behavioral tests first."
            ),
        }

    # Execute pytest to prove the suite is RED
    target_args = [str(contract_dir), str(behavioral_dir)]
    # Filter to existing directories
    existing_dirs = [d for d in target_args if Path(d).is_dir()]

    cmd = list(pytest_runner) + existing_dirs
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        pytest_exit = proc.returncode
        stdout = proc.stdout
    except OSError as err:
        return 2, {
            "valid": False,
            "subsystem": clean_subsystem,
            "error": f"Failed to execute pytest runner: {err}",
        }

    if pytest_exit == 0:
        return 1, {
            "valid": False,
            "subsystem": clean_subsystem,
            "error": (
                "Orthogonal test suite is NOT RED (pytest exited 0). "
                "The test suite must fail against unimplemented domain code before locking."
            ),
            "stdout": stdout,
        }

    # Compute manifest hashes
    file_hashes: dict[str, str] = {}
    for f in test_files:
        rel = f.relative_to(root).as_posix()
        file_hashes[rel] = _hash_file(f)

    manifest = {
        "subsystem": clean_subsystem,
        "locked_at": datetime.now(UTC).isoformat(),
        "pytest_exit_code": pytest_exit,
        "files": file_hashes,
    }

    out_dir = root / Path(state_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"{clean_subsystem}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return 0, {
        "valid": True,
        "subsystem": clean_subsystem,
        "manifest_file": manifest_path.relative_to(root).as_posix(),
        "locked_files_count": len(file_hashes),
        "files": list(file_hashes.keys()),
        "pytest_exit_code": pytest_exit,
    }


def check_red_lock(
    subsystem: str,
    state_dir: str | Path = DEFAULT_STATE_DIR,
    repo_root: str | Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Check that the locked orthogonal test suite has not been modified."""
    root = Path(repo_root or Path.cwd()).resolve()
    clean_subsystem = subsystem.strip()

    manifest_path = (root / Path(state_dir) / f"{clean_subsystem}.json").resolve()
    if not manifest_path.is_file():
        rel_str = (
            manifest_path.relative_to(root).as_posix()
            if manifest_path.is_relative_to(root)
            else str(manifest_path)
        )
        return 1, {
            "valid": False,
            "subsystem": clean_subsystem,
            "error": (
                f"RED lock manifest missing: '{rel_str}'. "
                "Phase 4 implementation ran without an active RED lock from Phase 3."
            ),
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as err:
        return 1, {
            "valid": False,
            "subsystem": clean_subsystem,
            "error": f"Corrupted RED lock manifest '{manifest_path}': {err}",
        }

    expected_files: dict[str, str] = manifest.get("files", {})
    current_files = _collect_orthogonal_test_files(clean_subsystem, root)
    current_hashes = {f.relative_to(root).as_posix(): _hash_file(f) for f in current_files}

    tampered: list[str] = []
    removed: list[str] = []
    added: list[str] = []

    for rel_path, expected_hash in expected_files.items():
        if rel_path not in current_hashes:
            removed.append(rel_path)
        elif current_hashes[rel_path] != expected_hash:
            tampered.append(rel_path)

    for rel_path in current_hashes:
        if rel_path not in expected_files:
            added.append(rel_path)

    if tampered or removed or added:
        return 1, {
            "valid": False,
            "subsystem": clean_subsystem,
            "error": "Orthogonal test suite was tampered with during implementation.",
            "tampered_files": tampered,
            "removed_files": removed,
            "added_files": added,
        }

    return 0, {
        "valid": True,
        "subsystem": clean_subsystem,
        "locked_files_count": len(expected_files),
        "files": list(expected_files.keys()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for verify_red_suite.py."""
    parser = argparse.ArgumentParser(
        description="Verify and lock orthogonal test suites before implementation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # lock command
    lock_parser = subparsers.add_parser("lock", help="Lock a failing RED test suite")
    lock_parser.add_argument("--subsystem", "-s", required=True, help="Subsystem name")
    lock_parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help="Directory to store RED lock manifests",
    )
    lock_parser.add_argument(
        "--root",
        "-r",
        help="Repository root path",
    )

    # check command
    check_parser = subparsers.add_parser("check", help="Verify locked test suite integrity")
    check_parser.add_argument("--subsystem", "-s", required=True, help="Subsystem name")
    check_parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help="Directory where RED lock manifests are stored",
    )
    check_parser.add_argument(
        "--root",
        "-r",
        help="Repository root path",
    )

    args = parser.parse_args(argv)

    if args.command == "lock":
        exit_code, report = lock_red_suite(
            subsystem=args.subsystem,
            state_dir=args.state_dir,
            repo_root=args.root,
        )
        print(json.dumps(report, indent=2))
        return exit_code

    if args.command == "check":
        exit_code, report = check_red_lock(
            subsystem=args.subsystem,
            state_dir=args.state_dir,
            repo_root=args.root,
        )
        print(json.dumps(report, indent=2))
        return exit_code

    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
