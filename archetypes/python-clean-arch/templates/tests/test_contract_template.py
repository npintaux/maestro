"""Contract test template: assert real responses against the frozen openapi.yaml.

The Independent Test Architect replaces ``_handle`` with a client call to the
real entrypoint and derives the expected status codes from the subsystem's
``openapi.yaml``. Assertions must compare an *observed* response to the contract;
never compare a literal against itself (e.g. ``assert 200 == 200``), which proves
nothing and is rejected by Gate 8 (``audit_test_coverage.py``).
"""

from __future__ import annotations

import pytest


def _handle(entity_id: str) -> tuple[int, dict[str, str]]:
    """Illustrative handler stand-in. Replace with a call to the real API."""
    if not entity_id:
        return 422, {"error": "entity_id is required."}
    if entity_id == "missing":
        return 404, {"error": "entity not found."}
    return 200, {"entity_id": entity_id}


@pytest.mark.parametrize(
    ("entity_id", "expected_status"),
    [("acc-1", 200), ("missing", 404), ("", 422)],
)
def test_contract_status_codes(entity_id: str, expected_status: int) -> None:
    """Every status code declared in openapi.yaml is exercised and asserted."""
    status, _body = _handle(entity_id)
    assert status == expected_status


def test_contract_prd_story_traceability() -> None:
    """User Story US-1: a valid lookup returns the entity payload with HTTP 200."""
    status, body = _handle("acc-1")
    assert status == 200
    assert body["entity_id"] == "acc-1"
