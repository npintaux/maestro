"""Unit tests for the Contract & Schema Validator (scripts/validate_contract.py)."""

import json
from pathlib import Path

import pytest

from scripts.validate_contract import (
    ContractAuditReport,
    SpecAuditReport,
    audit_contract_file,
    audit_contract_text,
    audit_spec_file,
    audit_spec_text,
    audit_subsystem,
    main,
)


@pytest.fixture
def valid_openapi_yaml() -> str:
    """Fixture providing a complete, compliant OpenAPI 3.0 specification."""
    return """openapi: 3.0.3
info:
  title: Invoicing Subsystem API
  version: 1.0.0
  description: API for managing customer invoices and calculating line items.
paths:
  /v1/invoices:
    post:
      operationId: createInvoice
      summary: Create and calculate a customer invoice
      description: Evaluates pricing rules and returns a calculated invoice.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InvoiceRequest'
      responses:
        '201':
          description: Invoice created successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InvoiceResponse'
        '400':
          description: Invalid invoice request payload
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
        '422':
          description: Unprocessable entity / business rule failure
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
        '500':
          description: Internal server error
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
components:
  schemas:
    InvoiceRequest:
      type: object
      required:
        - customer_id
        - amount_cents
      properties:
        customer_id:
          type: string
        amount_cents:
          type: integer
          minimum: 1
    InvoiceResponse:
      type: object
      required:
        - invoice_id
        - total_cents
        - status
      properties:
        invoice_id:
          type: string
        total_cents:
          type: integer
        status:
          type: string
    ErrorResponse:
      type: object
      required:
        - code
        - message
      properties:
        code:
          type: string
        message:
          type: string
"""


@pytest.fixture
def valid_spec_md() -> str:
    """Fixture providing a SPEC.md with a resolved 'decision-list' pattern declaration."""
    return """# Subsystem Specification: Invoicing (`src/modules/invoicing/`)

> **Status**: `FROZEN / SPEC-DRIVEN DEVELOPMENT BASELINE (Gate 1)`
> **Selected Domain Pattern**: `decision-list`
> **Target Implementer**: Developer Worker (`/implement`)

## 4. Domain Pattern Realization
### Selected Pattern: `decision-list`
* **Port / Abstract Base Class**: Defined in `src/domain/rules/base.py`.
* **Coordinator File**: `src/domain/engine.py` composes the ordered rule sequence.
"""


def test_audit_contract_text_valid(valid_openapi_yaml: str) -> None:
    """Verify that a compliant OpenAPI spec passes all validation checks."""
    report: ContractAuditReport = audit_contract_text(valid_openapi_yaml)
    assert report.is_valid is True
    assert len(report.violations) == 0
    assert len(report.endpoints_found) == 1
    assert "POST /v1/invoices" in report.endpoints_found
    assert len(report.schemas_found) == 3


def test_audit_contract_file_valid(
    tmp_path: Path,
    valid_openapi_yaml: str,
) -> None:
    """Verify auditing an actual file on disk."""
    file_path = tmp_path / "openapi.yaml"
    file_path.write_text(valid_openapi_yaml, encoding="utf-8")

    report = audit_contract_file(file_path)
    assert report.is_valid is True
    assert report.file_path == str(file_path)


def test_audit_contract_file_not_found(tmp_path: Path) -> None:
    """Verify error handling when contract file does not exist."""
    missing = tmp_path / "openapi.yaml"
    report = audit_contract_file(missing)
    assert report.is_valid is False
    assert any("File not found" in v for v in report.violations)


def test_audit_contract_empty_file(tmp_path: Path) -> None:
    """Verify error handling when contract file is empty."""
    empty = tmp_path / "openapi.yaml"
    empty.write_text("", encoding="utf-8")
    report = audit_contract_file(empty)
    assert report.is_valid is False
    assert any("empty" in v.lower() for v in report.violations)


def test_audit_contract_invalid_yaml() -> None:
    """Verify error handling on malformed YAML."""
    bad_yaml = "openapi: 3.0.0\npaths: [unclosed bracket"
    report = audit_contract_text(bad_yaml)
    assert report.is_valid is False
    assert any("Invalid YAML" in v for v in report.violations)


def test_audit_contract_non_dict_yaml() -> None:
    """Verify error handling when YAML is a list or scalar."""
    report = audit_contract_text("- just a list item")
    assert report.is_valid is False
    assert any("must be a mapping/dictionary" in v for v in report.violations)


def test_audit_contract_missing_openapi_version() -> None:
    """Verify failure when openapi version is missing or invalid."""
    spec = """info:
  title: Test
  version: 1.0.0
paths: {}
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("openapi: 3.x" in v for v in report.violations)


def test_audit_contract_missing_info() -> None:
    """Verify failure when info block or title/version is missing."""
    spec = """openapi: 3.0.0
paths: {}
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("info" in v.lower() for v in report.violations)


def test_audit_contract_no_paths() -> None:
    """Verify failure when paths block is empty or missing."""
    spec = """openapi: 3.0.0
info:
  title: Empty
  version: 1.0.0
paths: {}
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("No endpoints" in v for v in report.violations)


def test_audit_contract_unversioned_path() -> None:
    """Verify failure when an endpoint path is not versioned."""
    spec = """openapi: 3.0.0
info:
  title: Unversioned
  version: 1.0.0
paths:
  /invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses:
        '200':
          description: ok
        '500':
          description: error
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("must start with a version prefix" in v for v in report.violations)


def test_audit_contract_non_dict_path_item() -> None:
    """Verify handling when path item is not a dictionary."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices: "not a dictionary"
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False


def test_audit_contract_non_http_method_key() -> None:
    """Verify skipping non-HTTP method keys like parameters or summary under path."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    summary: Invoice Path
    get:
      operationId: listInvoices
      responses:
        '200':
          description: ok
        '400':
          description: bad request
        '500':
          description: server error
components:
  schemas:
    Invoice:
      type: object
      properties:
        id:
          type: string
"""
    report = audit_contract_text(spec)
    assert report.is_valid is True


def test_audit_contract_missing_operation_id() -> None:
    """Verify failure when an operation lacks an operationId."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      summary: List invoices
      responses:
        '200':
          description: ok
        '500':
          description: error
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("missing 'operationId'" in v for v in report.violations)


def test_audit_contract_empty_responses() -> None:
    """Verify failure when responses dictionary is empty or missing."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses: {}
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("must define response status codes" in v for v in report.violations)


def test_audit_contract_missing_2xx_response() -> None:
    """Verify failure when an operation lacks a 2xx success response."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses:
        '400':
          description: bad request
        '500':
          description: server error
components:
  schemas:
    Invoice:
      type: object
      properties:
        id:
          type: string
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("lacks a 2xx success response" in v for v in report.violations)


def test_audit_contract_missing_error_responses() -> None:
    """Verify failure when an operation lacks required error responses (4xx or 500)."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses:
        '200':
          description: ok
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("500" in v for v in report.violations)
    assert any("4xx" in v for v in report.violations)


def test_audit_contract_missing_schemas_section() -> None:
    """Verify failure when components.schemas is absent."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses:
        '200':
          description: ok
        '400':
          description: bad request
        '500':
          description: server error
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("components.schemas" in v for v in report.violations)


def test_audit_contract_unresolved_schema_ref() -> None:
    """Verify failure when a response/requestBody references a non-existent schema."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/MissingSchema'
        '400':
          description: bad
        '500':
          description: server error
components:
  schemas:
    ExistingSchema:
      type: object
      properties:
        id:
          type: string
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("MissingSchema" in v for v in report.violations)


def test_audit_contract_empty_object_schema() -> None:
    """Verify failure when a schema defines type: object with zero properties."""
    spec = """openapi: 3.0.0
info:
  title: Test
  version: 1.0.0
paths:
  /v1/invoices:
    get:
      operationId: listInvoices
      summary: List invoices
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EmptyModel'
        '400':
          description: bad
        '500':
          description: server error
components:
  schemas:
    EmptyModel:
      type: object
"""
    report = audit_contract_text(spec)
    assert report.is_valid is False
    assert any("EmptyModel" in v and "no properties" in v for v in report.violations)


def test_main_cli_success(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    valid_openapi_yaml: str,
    valid_spec_md: str,
) -> None:
    """Verify CLI exit code 0 when both openapi.yaml and sibling SPEC.md are valid."""
    (tmp_path / "openapi.yaml").write_text(valid_openapi_yaml, encoding="utf-8")
    (tmp_path / "SPEC.md").write_text(valid_spec_md, encoding="utf-8")

    exit_code = main([str(tmp_path / "openapi.yaml")])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True
    assert data["selected_pattern"] == "decision-list"


def test_main_cli_failure(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Verify CLI exit code 1 on invalid contract."""
    contract_file = tmp_path / "openapi.yaml"
    contract_file.write_text("openapi: 3.0.0\npaths: {}", encoding="utf-8")

    exit_code = main([str(contract_file)])
    assert exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False


def test_main_cli_missing_arg() -> None:
    """Verify CLI error on missing argument."""
    with pytest.raises(SystemExit):
        main([])


# --- SPEC.md domain-pattern gating ------------------------------------------------------------


def test_audit_spec_text_valid(valid_spec_md: str) -> None:
    """Verify a SPEC.md with a resolved, recognized pattern and its artifacts passes."""
    report: SpecAuditReport = audit_spec_text(valid_spec_md)
    assert report.is_valid is True
    assert report.selected_pattern == "decision-list"
    assert report.violations == []


def test_audit_spec_text_empty() -> None:
    """Verify an empty SPEC.md is rejected."""
    report = audit_spec_text("   \n  ")
    assert report.is_valid is False
    assert any("empty" in v for v in report.violations)


def test_audit_spec_text_missing_declaration() -> None:
    """Verify a SPEC.md lacking the pattern header is rejected."""
    report = audit_spec_text("# Subsystem Spec\n\nNo pattern header here.\n")
    assert report.is_valid is False
    assert report.selected_pattern is None
    assert any("missing" in v and "Selected Domain Pattern" in v for v in report.violations)


def test_audit_spec_text_unresolved_pattern_placeholder() -> None:
    """Verify the multi-option template placeholder for the pattern value is rejected."""
    content = (
        "> **Selected Domain Pattern**: "
        "`[decision-list | repository-service | state-machine "
        "| pipeline-reducer | algorithmic-core]`\n"
    )
    report = audit_spec_text(content)
    assert report.is_valid is False
    assert report.selected_pattern is None
    assert any("unresolved template placeholder" in v for v in report.violations)


def test_audit_spec_text_unrecognized_pattern() -> None:
    """Verify a made-up pattern name is rejected."""
    report = audit_spec_text("> **Selected Domain Pattern**: `event-sourcing`\n")
    assert report.is_valid is False
    assert report.selected_pattern is None
    assert any("not a recognized Maestro pattern" in v for v in report.violations)


def test_audit_spec_text_missing_required_artifact() -> None:
    """Verify a declared pattern that omits its required domain artifact is rejected."""
    content = (
        "> **Selected Domain Pattern**: `decision-list`\n\n"
        "Port defined in `src/domain/rules/base.py` but no coordinator file is named.\n"
    )
    report = audit_spec_text(content)
    assert report.is_valid is False
    assert report.selected_pattern == "decision-list"
    assert any("engine.py" in v for v in report.violations)


def test_audit_spec_text_unresolved_file_placeholder() -> None:
    """Verify a leftover '[fileA.py | fileB.py]' layout placeholder is rejected and cannot game
    the artifact check."""
    content = (
        "> **Selected Domain Pattern**: `state-machine`\n\n"
        "* **Port**: `src/domain/[rules/base.py | repository.py | state_machine.py | solver.py]`\n"
    )
    report = audit_spec_text(content)
    assert report.is_valid is False
    assert any("layout placeholder" in v for v in report.violations)
    # The placeholder's `state_machine.py` option must not satisfy the artifact requirement.
    assert any(
        "state_machine.py" in v and "required domain artifact" in v for v in report.violations
    )


def test_audit_spec_text_case_insensitive_pattern() -> None:
    """Verify the declared pattern value is matched case-insensitively and normalized."""
    content = (
        "> **Selected Domain Pattern**: `Repository-Service`\n\n"
        "Port in `src/domain/repository.py`, coordinated by `src/domain/service.py`.\n"
    )
    report = audit_spec_text(content)
    assert report.is_valid is True
    assert report.selected_pattern == "repository-service"


def test_audit_spec_file_not_found(tmp_path: Path) -> None:
    """Verify a missing SPEC.md file is reported as a Gate 1 failure."""
    report = audit_spec_file(tmp_path / "SPEC.md")
    assert report.is_valid is False
    assert any("not found" in v for v in report.violations)


def test_audit_spec_file_valid(tmp_path: Path, valid_spec_md: str) -> None:
    """Verify audit_spec_file reads and validates a real SPEC.md on disk."""
    spec_file = tmp_path / "SPEC.md"
    spec_file.write_text(valid_spec_md, encoding="utf-8")
    report = audit_spec_file(spec_file)
    assert report.is_valid is True
    assert report.selected_pattern == "decision-list"


def test_spec_audit_report_to_dict(valid_spec_md: str) -> None:
    """Verify SpecAuditReport.to_dict exposes the 'valid' alias and selected_pattern."""
    report = audit_spec_text(valid_spec_md)
    data = report.to_dict()
    assert data["valid"] is True
    assert data["selected_pattern"] == "decision-list"


def test_audit_subsystem_valid(tmp_path: Path, valid_openapi_yaml: str, valid_spec_md: str) -> None:
    """Verify the combined subsystem audit passes when contract and SPEC.md are both valid."""
    (tmp_path / "openapi.yaml").write_text(valid_openapi_yaml, encoding="utf-8")
    (tmp_path / "SPEC.md").write_text(valid_spec_md, encoding="utf-8")
    report = audit_subsystem(tmp_path / "openapi.yaml")
    assert report.is_valid is True
    assert report.selected_pattern == "decision-list"
    assert report.violations == []


def test_audit_subsystem_missing_spec(tmp_path: Path, valid_openapi_yaml: str) -> None:
    """Verify a valid contract still fails Gate 1 when the sibling SPEC.md is absent."""
    (tmp_path / "openapi.yaml").write_text(valid_openapi_yaml, encoding="utf-8")
    report = audit_subsystem(tmp_path / "openapi.yaml")
    assert report.is_valid is False
    assert report.selected_pattern is None
    assert any("SPEC.md not found" in v for v in report.violations)


def test_audit_subsystem_merges_both_violations(tmp_path: Path) -> None:
    """Verify contract and SPEC.md violations are merged into one report."""
    (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0\npaths: {}", encoding="utf-8")
    (tmp_path / "SPEC.md").write_text("# Spec with no pattern header\n", encoding="utf-8")
    report = audit_subsystem(tmp_path / "openapi.yaml")
    assert report.is_valid is False
    assert any("paths" in v for v in report.violations)
    assert any("Selected Domain Pattern" in v for v in report.violations)
