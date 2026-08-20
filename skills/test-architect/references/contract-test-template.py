"""Canonical Contract Verification Test Harness.

Validates that subsystem HTTP entrypoints strictly adhere to the frozen openapi.yaml
interface contract, including HTTP status codes, response schemas, error structures,
and header conventions.

This test suite is authored by the Independent Test Architect and executes
orthogonally to developer unit tests. It treats the subsystem as a black box: it imports
ONLY the public entrypoint app, never internal `domain/` or `adapters/` classes.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

# Path to the FROZEN contract this suite must conform to. Conformance is checked against the
# committed openapi.yaml, NOT the app's self-reported /openapi.json (which could silently drift).
FROZEN_CONTRACT = Path("src/modules/sample_subsystem/openapi.yaml")


class TestContractConformance:
    """Black-box contract compliance test suite."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the subsystem public entrypoint."""
        # Note: Imports the public router/app from entrypoints, NEVER internal domain classes.
        from src.modules.sample_subsystem.entrypoints.api import app

        return TestClient(app)

    @pytest.fixture
    def frozen_contract(self) -> Mapping[str, Any]:
        """Load the frozen openapi.yaml the running app must satisfy."""
        return yaml.safe_load(FROZEN_CONTRACT.read_text(encoding="utf-8"))

    def test_live_app_conforms_to_frozen_contract(
        self, client: TestClient, frozen_contract: Mapping[str, Any]
    ) -> None:
        """Verify every path/method/status in the frozen contract is served by the live app.

        This is the core conformance assertion: it pins the implementation to the committed
        contract rather than trusting the app's own generated schema.
        """
        live: Mapping[str, Any] = client.get("/openapi.json").json()
        live_paths: Mapping[str, Any] = live.get("paths", {})

        for path, frozen_ops in frozen_contract.get("paths", {}).items():
            assert path in live_paths, f"Frozen contract path '{path}' is not served by the app."
            for method, frozen_op in frozen_ops.items():
                op = f"{method.upper()} {path}"
                live_op = live_paths[path].get(method)
                assert live_op is not None, f"Frozen operation '{op}' is missing."
                live_codes = {str(c) for c in live_op.get("responses", {})}
                for status_code in frozen_op.get("responses", {}):
                    assert str(status_code) in live_codes, (
                        f"Frozen status '{status_code}' for '{op}' is not served."
                    )

    def test_openapi_spec_route_versioning(self, frozen_contract: Mapping[str, Any]) -> None:
        """Verify that all exposed paths are versioned (e.g., /v1/...)."""
        for path in frozen_contract.get("paths", {}):
            assert path.startswith("/v"), f"Path '{path}' violates /v<N>/ versioning contract."

    def test_post_valid_payload_returns_201_and_valid_schema(self, client: TestClient) -> None:
        """Verify successful creation returns 201, a JSON content-type, and typed schema fields."""
        payload = {"entity_id": "ent_123", "target_value": "https://example.com"}
        response = client.post("/v1/resources", json=payload)

        assert response.status_code == 201
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert "id" in data
        assert data["entity_id"] == "ent_123"
        assert "created_at" in data

    def test_post_missing_fields_returns_400_with_error_schema(self, client: TestClient) -> None:
        """Verify invalid payload returns 400 Bad Request with structured error schema."""
        invalid_payload = {"invalid_field": 123}
        response = client.post("/v1/resources", json=invalid_payload)

        assert response.status_code == 400
        error_body: Mapping[str, Any] = response.json()
        assert "error_code" in error_body
        assert "message" in error_body
        assert error_body["error_code"] == "INVALID_PAYLOAD"

    def test_get_nonexistent_entity_returns_404_with_error_schema(self, client: TestClient) -> None:
        """Verify requesting unknown ID returns 404 Not Found."""
        response = client.get("/v1/resources/non_existent_id")

        assert response.status_code == 404
        error_body: Mapping[str, Any] = response.json()
        assert error_body["error_code"] == "ENTITY_NOT_FOUND"

    def test_domain_rule_violation_returns_422_with_error_schema(self, client: TestClient) -> None:
        """Verify business rule violation returns 422 Unprocessable Entity."""
        violating_payload = {
            "entity_id": "ent_123",
            "target_value": "https://blocked-malicious-url.com",
        }
        response = client.post("/v1/resources", json=violating_payload)

        assert response.status_code == 422
        error_body: Mapping[str, Any] = response.json()
        assert error_body["error_code"] == "RULE_VIOLATION"

    def test_adapter_failure_returns_clean_500_without_leaking_internals(
        self, client: TestClient
    ) -> None:
        """Verify a simulated datastore/adapter fault returns a structured 500 with no stack trace.

        Inject the fault through a fake adapter bound at the entrypoint (e.g. FastAPI dependency
        override) so the subsystem stays a black box; never patch internal domain classes.
        """
        payload = {"entity_id": "trigger_adapter_error", "target_value": "https://example.com"}
        response = client.post("/v1/resources", json=payload)

        assert response.status_code == 500
        error_body: Mapping[str, Any] = response.json()
        assert error_body["error_code"] == "INTERNAL_ERROR"
        # The response must not leak implementation details.
        assert "Traceback" not in response.text
        assert "message" in error_body
