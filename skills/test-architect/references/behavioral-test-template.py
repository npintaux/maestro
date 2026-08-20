"""Canonical Behavioral Verification Test Harness.

Tests end-to-end user stories and acceptance criteria defined in docs/PRD.md and
subsystem SPEC.md.

Every test method maps directly to a PRD User Story (e.g. US-1) and Acceptance
Criterion (e.g. AC-1.2) for strict end-to-end traceability.

NOTE: The US-1/US-2/US-3 groups below are per-pattern *exemplars* (decision-list validation,
state-machine lifecycle, algorithmic solver) drawn from different subsystems to illustrate the
style. A real behavioral suite covers exactly the User Stories its own SPEC.md claims.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient


class TestBehavioralAcceptance:
    """End-to-end user story and acceptance criteria verification."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the subsystem public entrypoint."""
        from src.modules.sample_subsystem.entrypoints.api import app

        return TestClient(app)

    # --- User Story US-1: Resource Creation & Validation (AC-1.1, AC-1.2, AC-1.3) ---

    def test_us1_ac1_1_successful_creation_generates_unique_identifier(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.1] Submitting a valid URL generates a unique short code."""
        response = client.post("/v1/urls", json={"original_url": "https://docs.cloud.google.com"})
        assert response.status_code == 201
        data: Mapping[str, Any] = response.json()
        assert len(data["short_code"]) == 7
        assert data["original_url"] == "https://docs.cloud.google.com"

    def test_us1_ac1_2_malformed_url_rejected_with_validation_error(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.2] Submitting a malformed URL returns 400 Bad Request."""
        response = client.post("/v1/urls", json={"original_url": "ftp://not-http-url"})
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert data["error_code"] == "INVALID_PAYLOAD"

    def test_us1_ac1_3_safe_browsing_flagged_domain_rejected(self, client: TestClient) -> None:
        """[US-1][AC-1.3] URLs flagged by security checks return 422 Unprocessable."""
        response = client.post(
            "/v1/urls", json={"original_url": "https://malware.testing.google.test"}
        )
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["error_code"] == "RULE_VIOLATION"

    # --- User Story US-2: State Machine Lifecycle (AC-2.1, AC-2.2) ---

    def test_us2_ac2_1_valid_lifecycle_transition(self, client: TestClient) -> None:
        """[US-2][AC-2.1] Order transitions from PENDING to RESERVED upon inventory hold."""
        response = client.post("/v1/orders/ord_100/transitions", json={"event": "RESERVE"})
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["current_state"] == "RESERVED"

    def test_us2_ac2_2_invalid_lifecycle_transition_returns_409_conflict(
        self, client: TestClient
    ) -> None:
        """[US-2][AC-2.2] Attempting to ship a CANCELLED order returns 409 Conflict."""
        # Setup cancelled order
        client.post("/v1/orders/ord_200/transitions", json={"event": "CANCEL"})

        # Attempt illegal transition
        response = client.post("/v1/orders/ord_200/transitions", json={"event": "SHIP"})
        assert response.status_code == 409
        data: Mapping[str, Any] = response.json()
        assert data["error_code"] == "STATE_CONFLICT"

    # --- User Story US-3: Algorithmic Resolution & Determinism (AC-3.1) ---

    def test_us3_ac3_1_deterministic_route_solver_calculates_shortest_path(
        self, client: TestClient
    ) -> None:
        """[US-3][AC-3.1] Route solver deterministically computes optimal cost and path."""
        payload = {
            "nodes": ["A", "B", "C"],
            "edges": {"A": {"B": 1.0, "C": 5.0}, "B": {"C": 2.0}},
            "start_node": "A",
            "target_node": "C",
        }
        response = client.post("/v1/routes/solve", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["optimal_path"] == ["A", "B", "C"]
        assert data["total_cost"] == 3.0
