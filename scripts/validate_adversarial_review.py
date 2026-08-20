"""Mechanical Validator for Structured Adversarial Architecture Reviews.

Enforces mechanical adversarial review completion before Gate 0.5 Human Approval:
1. Verifies that all required critic lenses (e.g., resilience, cost, simplicity) have fired
   and produced structured objections in `docs/adr/objections/<critic>.json`.
2. Verifies that every objection is well-formed and references a valid ADR.
3. Verifies that `docs/adr/objections/resolutions.json` exists and that EVERY objection ID
   has a complete, non-placeholder, disposition-tagged resolution traceable to an updated ADR.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path so validate_adrs can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_adrs import _is_placeholder_value  # noqa: E402

VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_DISPOSITIONS = {"mitigated", "accepted-risk", "rejected"}
DEFAULT_REQUIRED_CRITICS = ["resilience", "cost", "simplicity"]


def _normalize_adr_id(raw_id: str | int | None) -> str | None:
    """Normalize ADR identifier to 4-digit zero-padded string (e.g. '0002' -> '0002')."""
    if raw_id is None:
        return None
    s = str(raw_id).strip()
    match = re.search(r"(?:ADR-)?(\d+)", s, re.IGNORECASE)
    if match:
        try:
            return f"{int(match.group(1)):04d}"
        except ValueError:
            return None
    return None


def _get_existing_adr_ids(adr_dir: Path) -> set[str]:
    """Extract all valid ADR IDs from an ADR directory."""
    if not adr_dir.exists() or not adr_dir.is_dir():
        return set()

    adr_ids: set[str] = set()
    for md_file in adr_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            title_match = re.search(
                r"^#\s+\[?(?:ADR-)?(\d{1,4})\]?[:\s]+", content, re.MULTILINE | re.IGNORECASE
            )
            if title_match:
                adr_ids.add(f"{int(title_match.group(1)):04d}")
        except OSError:
            continue
    return adr_ids


def validate_adversarial_review(
    objections_dir: str | Path,
    required_critics: Sequence[str] = DEFAULT_REQUIRED_CRITICS,
    adr_dir: str | Path | None = "docs/adr",
) -> tuple[int, dict[str, Any]]:
    """Validate all critic objections and architect resolutions for completeness.

    Args:
        objections_dir: Directory containing <critic>.json files and resolutions.json.
        required_critics: List of critic names that must have produced objections.
        adr_dir: Optional path to ADR directory for ADR ID cross-referencing.

    Returns:
        Tuple of (exit_code, report_dict).
    """
    obj_path = Path(objections_dir)
    errors: list[str] = []

    if not obj_path.exists() or not obj_path.is_dir():
        return 1, {
            "valid": False,
            "error": (
                f"Objections directory '{objections_dir}' does not exist or is not a directory."
            ),
            "errors": [f"Directory '{objections_dir}' not found."],
        }

    known_adr_ids: set[str] = set()
    if adr_dir:
        adr_path = Path(adr_dir)
        known_adr_ids = _get_existing_adr_ids(adr_path)

    # 1. Verify required critics
    critic_files: dict[str, Path] = {}
    for f in obj_path.glob("*.json"):
        if f.name != "resolutions.json":
            critic_files[f.stem] = f

    if not critic_files:
        return 1, {
            "valid": False,
            "error": f"No critic objections files found in '{objections_dir}'.",
            "errors": ["No critic objection JSON files present."],
        }

    for req in required_critics:
        req_clean = req.strip()
        if req_clean not in critic_files:
            errors.append(
                f"Missing required critic file: '{req_clean}.json' not found in '{objections_dir}'."
            )

    all_objections: dict[str, dict[str, Any]] = {}  # objection_id -> objection_data
    critic_counts: dict[str, int] = {}

    # 2. Parse and validate each critic file
    for critic_name, filepath in sorted(critic_files.items()):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            errors.append(f"Failed to parse critic file '{filepath.name}': {err}")
            continue

        if not isinstance(data, dict):
            errors.append(f"Critic file '{filepath.name}' must contain a JSON object.")
            continue

        objections = data.get("objections")
        if not isinstance(objections, list) or len(objections) == 0:
            errors.append(
                f"Critic '{critic_name}' in '{filepath.name}' has no objections "
                "(must be a non-empty list)."
            )
            continue

        critic_counts[critic_name] = len(objections)

        for idx, obj in enumerate(objections):
            if not isinstance(obj, dict):
                errors.append(f"Objection #{idx + 1} in '{filepath.name}' is not an object.")
                continue

            obj_id = obj.get("id")
            if not obj_id or not isinstance(obj_id, str) or _is_placeholder_value(obj_id):
                errors.append(f"Objection #{idx + 1} in '{filepath.name}' is missing a valid 'id'.")
                continue

            if obj_id in all_objections:
                prev_file = all_objections[obj_id]["file"]
                errors.append(
                    f"Duplicate objection id '{obj_id}' found in '{filepath.name}' "
                    f"(already defined in '{prev_file}')."
                )
            else:
                all_objections[obj_id] = {
                    "data": obj,
                    "file": filepath.name,
                    "critic": critic_name,
                }

            severity = str(obj.get("severity", "")).strip().lower()
            if severity not in VALID_SEVERITIES:
                valid_sev_str = ", ".join(sorted(VALID_SEVERITIES))
                errors.append(
                    f"Objection '{obj_id}' in '{filepath.name}' has invalid severity "
                    f"'{severity}'. Must be one of: {valid_sev_str}."
                )

            claim = obj.get("claim")
            if not claim or not isinstance(claim, str) or _is_placeholder_value(claim):
                errors.append(
                    f"Objection '{obj_id}' in '{filepath.name}' has empty or placeholder 'claim'."
                )

            challenged_adr_raw = obj.get("challenged_adr")
            norm_adr = _normalize_adr_id(challenged_adr_raw)
            if not norm_adr:
                errors.append(
                    f"Objection '{obj_id}' in '{filepath.name}' has missing or "
                    "invalid 'challenged_adr'."
                )
            elif known_adr_ids and norm_adr not in known_adr_ids:
                known_str = ", ".join(sorted(known_adr_ids))
                errors.append(
                    f"Objection '{obj_id}' in '{filepath.name}' references non-existent "
                    f"ADR '{challenged_adr_raw}' (normalized '{norm_adr}'). Existing: {known_str}."
                )

    # 3. Parse and validate resolutions.json
    resolutions_file = obj_path / "resolutions.json"
    resolved_ids: set[str] = set()

    if not resolutions_file.exists():
        errors.append(f"Missing mandatory resolutions file: '{resolutions_file.name}' not found.")
    else:
        try:
            res_data = json.loads(resolutions_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            errors.append(f"Failed to parse '{resolutions_file.name}': {err}")
            res_data = None

        if isinstance(res_data, dict):
            resolutions_list = res_data.get("resolutions")
            if not isinstance(resolutions_list, list):
                errors.append(f"'{resolutions_file.name}' must contain a 'resolutions' array.")
            else:
                for idx, res in enumerate(resolutions_list):
                    if not isinstance(res, dict):
                        errors.append(
                            f"Resolution #{idx + 1} in '{resolutions_file.name}' is not an object."
                        )
                        continue

                    obj_id = res.get("objection_id")
                    if not obj_id or not isinstance(obj_id, str):
                        errors.append(
                            f"Resolution #{idx + 1} in '{resolutions_file.name}' "
                            "is missing 'objection_id'."
                        )
                        continue

                    resolved_ids.add(obj_id)

                    if obj_id not in all_objections:
                        errors.append(
                            f"Resolution #{idx + 1} references unknown objection_id '{obj_id}'."
                        )

                    disposition = str(res.get("disposition", "")).strip().lower()
                    if disposition not in VALID_DISPOSITIONS:
                        valid_disp_str = ", ".join(sorted(VALID_DISPOSITIONS))
                        errors.append(
                            f"Resolution for '{obj_id}' has invalid disposition '{disposition}'. "
                            f"Must be one of: {valid_disp_str}."
                        )

                    resolution_text = res.get("resolution")
                    if (
                        not resolution_text
                        or not isinstance(resolution_text, str)
                        or _is_placeholder_value(resolution_text)
                    ):
                        errors.append(
                            f"Resolution for '{obj_id}' has empty or placeholder 'resolution' text."
                        )

                    adr_updated_raw = res.get("adr_updated")
                    norm_updated_adr = _normalize_adr_id(adr_updated_raw)
                    if not norm_updated_adr:
                        errors.append(
                            f"Resolution for '{obj_id}' has missing or invalid 'adr_updated'."
                        )
                    elif known_adr_ids and norm_updated_adr not in known_adr_ids:
                        errors.append(
                            f"Resolution for '{obj_id}' references non-existent updated ADR "
                            f"'{adr_updated_raw}' (normalized '{norm_updated_adr}')."
                        )

    # 4. Check for unresolved objections
    unresolved = [oid for oid in all_objections if oid not in resolved_ids]
    if unresolved:
        errors.append(
            f"Unresolved objections ({len(unresolved)}): {', '.join(sorted(unresolved))}. "
            f"Every objection must have a matching entry in '{resolutions_file.name}'."
        )

    is_valid = len(errors) == 0
    report: dict[str, Any] = {
        "valid": is_valid,
        "objections_count": len(all_objections),
        "critic_counts": critic_counts,
        "resolved_count": len(resolved_ids),
        "unresolved_count": len(unresolved),
        "unresolved_ids": sorted(unresolved),
    }
    if not is_valid:
        report["errors"] = errors

    return (0 if is_valid else 1), report


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for validate_adversarial_review.py."""
    parser = argparse.ArgumentParser(
        description="Validate adversarial architecture review objections and resolutions."
    )
    parser.add_argument(
        "objections_dir",
        help="Path to directory containing <critic>.json files and resolutions.json",
    )
    parser.add_argument(
        "--required-critics",
        default=",".join(DEFAULT_REQUIRED_CRITICS),
        help="Comma-separated list of required critic names (e.g. resilience,cost,simplicity)",
    )
    parser.add_argument(
        "--adr-dir",
        default="docs/adr",
        help="Path to ADR markdown directory for validating referenced ADR IDs",
    )

    args = parser.parse_args(argv)

    critics = [c.strip() for c in args.required_critics.split(",") if c.strip()]
    exit_code, report = validate_adversarial_review(
        objections_dir=args.objections_dir,
        required_critics=critics,
        adr_dir=args.adr_dir,
    )

    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
