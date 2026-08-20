"""Unit tests for validate_adversarial_review.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_adversarial_review import main, validate_adversarial_review


def _create_sample_adr(adr_dir: Path, adr_id: str = "0001", title: str = "Use Cloud Run") -> Path:
    """Create a minimal valid ADR file."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    adr_file = adr_dir / f"{adr_id}-{title.lower().replace(' ', '-')}.md"
    content = f"""# [{adr_id}] {title}

* **Status**: accepted
* **Date**: 2026-08-20

## Context and Problem Statement
We need a compute runtime.

## Decision Drivers
- Serverless scalability

## Considered Options
- Cloud Run
- GKE

## Decision Outcome
Chosen Cloud Run.

## Consequences
### Positive Consequences
- Low maintenance

## Pros and Cons of the Options
### Cloud Run
* Good: Fast deploy
"""
    adr_file.write_text(content, encoding="utf-8")
    return adr_file


def _setup_valid_objections(
    obj_dir: Path,
    adr_id: str = "0001",
) -> None:
    """Set up valid critic objection JSON files and resolutions.json."""
    obj_dir.mkdir(parents=True, exist_ok=True)

    # 1. resilience.json
    resilience_data = {
        "critic": "resilience",
        "objections": [
            {
                "id": "RES-001",
                "severity": "high",
                "challenged_adr": adr_id,
                "claim": "Pub/Sub at-least-once delivery is not deduplicated.",
            }
        ],
    }
    (obj_dir / "resilience.json").write_text(json.dumps(resilience_data), encoding="utf-8")

    # 2. cost.json
    cost_data = {
        "critic": "cost",
        "objections": [
            {
                "id": "CST-001",
                "severity": "medium",
                "challenged_adr": adr_id,
                "claim": "Multi-region replication will double egress costs unnecessarily.",
            }
        ],
    }
    (obj_dir / "cost.json").write_text(json.dumps(cost_data), encoding="utf-8")

    # 3. simplicity.json
    simplicity_data = {
        "critic": "simplicity",
        "objections": [
            {
                "id": "SMP-001",
                "severity": "low",
                "challenged_adr": adr_id,
                "claim": (
                    "Introducing Redis for caching adds operational overhead "
                    "before traffic demands it."
                ),
            }
        ],
    }
    (obj_dir / "simplicity.json").write_text(json.dumps(simplicity_data), encoding="utf-8")

    # 4. resolutions.json
    resolutions_data = {
        "resolutions": [
            {
                "objection_id": "RES-001",
                "disposition": "mitigated",
                "resolution": "Added idempotency key check in database transaction.",
                "adr_updated": adr_id,
            },
            {
                "objection_id": "CST-001",
                "disposition": "accepted-risk",
                "resolution": "Single-region deployment selected for Phase 1 to cap egress costs.",
                "adr_updated": adr_id,
            },
            {
                "objection_id": "SMP-001",
                "disposition": "mitigated",
                "resolution": (
                    "Deferred Redis cache; using in-memory LRU cache inside Cloud Run instance."
                ),
                "adr_updated": adr_id,
            },
        ]
    }
    (obj_dir / "resolutions.json").write_text(json.dumps(resolutions_data), encoding="utf-8")


def test_missing_objections_dir_fails(tmp_path: Path) -> None:
    """Verify failure when objections directory does not exist."""
    code, report = validate_adversarial_review(tmp_path / "nonexistent_dir")
    assert code == 1
    assert report["valid"] is False


def test_empty_objections_dir_fails(tmp_path: Path) -> None:
    """Verify failure when objections directory has no JSON files."""
    empty_dir = tmp_path / "empty_obj"
    empty_dir.mkdir()
    code, report = validate_adversarial_review(empty_dir)
    assert code == 1
    assert report["valid"] is False


def test_missing_required_critic_file_fails(tmp_path: Path) -> None:
    """Verify failure when a required critic file is missing."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    # Delete cost.json
    (obj_dir / "cost.json").unlink()

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("Missing required critic file: 'cost.json'" in e for e in report["errors"])


def test_critic_empty_objections_list_fails(tmp_path: Path) -> None:
    """Verify failure when a critic file has an empty objections array."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    # Empty resilience objections
    (obj_dir / "resilience.json").write_text(
        json.dumps({"critic": "resilience", "objections": []}), encoding="utf-8"
    )

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("has no objections" in e for e in report["errors"])


def test_critic_malformed_objection_missing_id_fails(tmp_path: Path) -> None:
    """Verify failure when an objection is missing an ID."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    (obj_dir / "resilience.json").write_text(
        json.dumps(
            {
                "critic": "resilience",
                "objections": [
                    {"severity": "high", "challenged_adr": "0001", "claim": "Valid claim"}
                ],
            }
        ),
        encoding="utf-8",
    )

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("missing a valid 'id'" in e for e in report["errors"])


def test_critic_duplicate_objection_id_fails(tmp_path: Path) -> None:
    """Verify failure when duplicate objection IDs exist across critic files."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    # Overwrite cost.json with duplicate RES-001 id
    (obj_dir / "cost.json").write_text(
        json.dumps(
            {
                "critic": "cost",
                "objections": [
                    {
                        "id": "RES-001",
                        "severity": "medium",
                        "challenged_adr": "0001",
                        "claim": "Duplicate ID",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("Duplicate objection id 'RES-001'" in e for e in report["errors"])


def test_critic_invalid_severity_fails(tmp_path: Path) -> None:
    """Verify failure when an objection has an invalid severity."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    (obj_dir / "resilience.json").write_text(
        json.dumps(
            {
                "critic": "resilience",
                "objections": [
                    {
                        "id": "RES-001",
                        "severity": "apocalyptic",
                        "challenged_adr": "0001",
                        "claim": "Catastrophic issue",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("invalid severity 'apocalyptic'" in e for e in report["errors"])


def test_critic_placeholder_claim_fails(tmp_path: Path) -> None:
    """Verify failure when an objection claim is a placeholder."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    (obj_dir / "resilience.json").write_text(
        json.dumps(
            {
                "critic": "resilience",
                "objections": [
                    {
                        "id": "RES-001",
                        "severity": "high",
                        "challenged_adr": "0001",
                        "claim": "{describe objection here}",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("empty or placeholder 'claim'" in e for e in report["errors"])


def test_critic_nonexistent_challenged_adr_fails(tmp_path: Path) -> None:
    """Verify failure when challenged ADR does not exist in ADR directory."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    (obj_dir / "resilience.json").write_text(
        json.dumps(
            {
                "critic": "resilience",
                "objections": [
                    {
                        "id": "RES-001",
                        "severity": "high",
                        "challenged_adr": "0099",
                        "claim": "Valid claim",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("references non-existent ADR '0099'" in e for e in report["errors"])


def test_missing_resolutions_file_fails(tmp_path: Path) -> None:
    """Verify failure when resolutions.json is missing."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    (obj_dir / "resolutions.json").unlink()

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("Missing mandatory resolutions file" in e for e in report["errors"])


def test_unresolved_objection_fails(tmp_path: Path) -> None:
    """Verify failure when an objection ID is missing from resolutions.json."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    # Remove SMP-001 resolution
    resolutions_data = {
        "resolutions": [
            {
                "objection_id": "RES-001",
                "disposition": "mitigated",
                "resolution": "Mitigated RES",
                "adr_updated": "0001",
            },
            {
                "objection_id": "CST-001",
                "disposition": "accepted-risk",
                "resolution": "Accepted CST",
                "adr_updated": "0001",
            },
        ]
    }
    (obj_dir / "resolutions.json").write_text(json.dumps(resolutions_data), encoding="utf-8")

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert "SMP-001" in report["unresolved_ids"]


def test_resolution_invalid_disposition_fails(tmp_path: Path) -> None:
    """Verify failure when a resolution has an invalid disposition."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    resolutions_data = {
        "resolutions": [
            {
                "objection_id": "RES-001",
                "disposition": "ignored-by-architect",
                "resolution": "Valid resolution text",
                "adr_updated": "0001",
            },
            {
                "objection_id": "CST-001",
                "disposition": "accepted-risk",
                "resolution": "Accepted CST",
                "adr_updated": "0001",
            },
            {
                "objection_id": "SMP-001",
                "disposition": "mitigated",
                "resolution": "Mitigated SMP",
                "adr_updated": "0001",
            },
        ]
    }
    (obj_dir / "resolutions.json").write_text(json.dumps(resolutions_data), encoding="utf-8")

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("invalid disposition 'ignored-by-architect'" in e for e in report["errors"])


def test_resolution_placeholder_text_fails(tmp_path: Path) -> None:
    """Verify failure when resolution text contains a placeholder."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    resolutions_data = {
        "resolutions": [
            {
                "objection_id": "RES-001",
                "disposition": "mitigated",
                "resolution": "TODO",
                "adr_updated": "0001",
            },
            {
                "objection_id": "CST-001",
                "disposition": "accepted-risk",
                "resolution": "Accepted CST",
                "adr_updated": "0001",
            },
            {
                "objection_id": "SMP-001",
                "disposition": "mitigated",
                "resolution": "Mitigated SMP",
                "adr_updated": "0001",
            },
        ]
    }
    (obj_dir / "resolutions.json").write_text(json.dumps(resolutions_data), encoding="utf-8")

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 1
    assert report["valid"] is False
    assert any("placeholder 'resolution' text" in e for e in report["errors"])


def test_happy_path_all_valid(tmp_path: Path) -> None:
    """Verify complete valid adversarial review passes with exit 0."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    code, report = validate_adversarial_review(obj_dir, adr_dir=adr_dir)
    assert code == 0
    assert report["valid"] is True
    assert report["objections_count"] == 3
    assert report["resolved_count"] == 3
    assert report["unresolved_count"] == 0


def test_cli_main_success_and_failure(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI exit codes and output formatting."""
    adr_dir = tmp_path / "docs" / "adr"
    _create_sample_adr(adr_dir, "0001")
    obj_dir = tmp_path / "docs" / "adr" / "objections"
    _setup_valid_objections(obj_dir, "0001")

    # 1. Success
    exit_code = main([str(obj_dir), "--adr-dir", str(adr_dir)])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True

    # 2. Failure
    (obj_dir / "cost.json").unlink()
    fail_code = main([str(obj_dir), "--adr-dir", str(adr_dir)])
    assert fail_code == 1
    captured_fail = capsys.readouterr()
    data_fail = json.loads(captured_fail.out)
    assert data_fail["valid"] is False
