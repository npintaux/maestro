"""Unit tests for the Independent Test Coverage Auditor (scripts/audit_test_coverage.py)."""

import json
from pathlib import Path

import pytest

from scripts.audit_test_coverage import (
    CoverageAuditReport,
    audit_subsystem_tests,
    audit_test_coverage,
    main,
)

OPENAPI = """openapi: 3.0.3
info:
  title: Shortener API
  version: 1.0.0
paths:
  /v1/urls:
    post:
      operationId: createUrl
      responses:
        '201':
          description: created
        '400':
          description: bad
        '422':
          description: rule violation
        '500':
          description: server error
        default:
          description: fallback
"""

SPEC = """# Subsystem Specification: shortener_api

> **Selected Domain Pattern**: `decision-list`

| Component | US |
|---|---|
| C1 | US-1 (AC-1.1) |
| C2 | US-2 (AC-2.1) |
"""

PRD = """# PRD

## US-1: Create short URL
## US-2: Reject malicious URL
## US-3: Redirect resolution (other subsystem)
"""

CONTRACT_TEST = """from src.modules.shortener_api.entrypoints.api import app


def test_created() -> None:
    assert response.status_code == 201


def test_bad() -> None:
    assert response.status_code == 400


def test_rule() -> None:
    assert response.status_code == 422


def test_server_error() -> None:
    assert response.status_code == 500
"""

BEHAVIORAL_TEST = '''from src.modules.shortener_api.entrypoints.api import app


def test_us1_ac1_1_create() -> None:
    """[US-1][AC-1.1] happy path."""
    assert True


def test_us2_ac2_1_reject() -> None:
    """[US-2][AC-2.1] rejection path."""
    assert True
'''


def _core(**overrides: str) -> CoverageAuditReport:
    """Invoke the pure core with valid defaults, overriding named documents."""
    kwargs: dict[str, str] = {
        "openapi_text": OPENAPI,
        "spec_text": SPEC,
        "contract_test_text": CONTRACT_TEST,
        "behavioral_test_text": BEHAVIORAL_TEST,
        "prd_text": PRD,
        "subsystem": "shortener_api",
    }
    kwargs.update(overrides)
    return audit_test_coverage(**kwargs)


def test_fully_covered_suite_passes() -> None:
    """Verify a suite covering all status codes and claimed stories is valid."""
    report = _core()
    assert report.is_valid is True
    assert report.violations == []
    assert report.documented_status_codes == ["201", "400", "422", "500"]
    assert report.covered_status_codes == ["201", "400", "422", "500"]
    assert report.claimed_story_ids == ["US-1", "US-2"]
    assert report.covered_story_ids == ["US-1", "US-2"]


def test_missing_status_code_assertion_fails() -> None:
    """Verify an undocumented-in-tests status code is flagged."""
    thin_contract = """from src.modules.shortener_api.entrypoints.api import app


def test_created() -> None:
    assert response.status_code == 201
"""
    report = _core(contract_test_text=thin_contract)
    assert report.is_valid is False
    assert any("'400'" in v and "no contract test asserts it" in v for v in report.violations)
    assert any("'500'" in v for v in report.violations)


def test_missing_behavioral_story_fails() -> None:
    """Verify a claimed story with no behavioral reference is flagged."""
    thin_behavioral = '''from src.modules.shortener_api.entrypoints.api import app


def test_us1_only() -> None:
    """[US-1][AC-1.1] only story 1."""
    assert True
'''
    report = _core(behavioral_test_text=thin_behavioral)
    assert report.is_valid is False
    assert any("'US-2'" in v and "no behavioral test references it" in v for v in report.violations)


def test_spec_claims_unknown_story_fails() -> None:
    """Verify a SPEC story absent from the PRD is flagged as a traceability break."""
    spec = "> **Selected Domain Pattern**: `decision-list`\n\n| C1 | US-9 (AC-9.1) |\n"
    behavioral = '''def test_us9() -> None:
    """[US-9] covers story 9."""
    assert True
'''
    report = _core(spec_text=spec, behavioral_test_text=behavioral)
    assert report.is_valid is False
    assert any("'US-9'" in v and "not defined in docs/PRD.md" in v for v in report.violations)


def test_spec_with_no_stories_fails() -> None:
    """Verify a SPEC declaring no User Stories cannot pass the coverage gate."""
    report = _core(spec_text="> **Selected Domain Pattern**: `repository-service`\n")
    assert report.is_valid is False
    assert any("declares no PRD User Stories" in v for v in report.violations)


def test_missing_contract_suite_fails() -> None:
    """Verify an empty contract suite is flagged."""
    report = _core(contract_test_text="   ", contract_path="tests/contract/x.py")
    assert report.is_valid is False
    assert any("Contract test suite is missing or empty" in v for v in report.violations)


def test_missing_behavioral_suite_fails() -> None:
    """Verify an empty behavioral suite is flagged."""
    report = _core(behavioral_test_text="", behavioral_path="tests/behavioral/x.py")
    assert report.is_valid is False
    assert any("Behavioral test suite is missing or empty" in v for v in report.violations)


def test_empty_openapi_flags_status_parse() -> None:
    """Verify an empty openapi.yaml is flagged rather than silently passing."""
    report = _core(openapi_text="   ")
    assert report.is_valid is False
    assert any("openapi.yaml is missing or empty" in v for v in report.violations)


def test_malformed_openapi_flags_parse_error() -> None:
    """Verify unparseable openapi.yaml is flagged."""
    report = _core(openapi_text="paths: [unclosed")
    assert report.is_valid is False
    assert any("Could not parse openapi.yaml" in v for v in report.violations)


def test_openapi_non_dict_and_odd_shapes_yield_no_codes() -> None:
    """Verify non-dict specs and malformed path/operation nodes contribute no status codes."""
    report = _core(
        openapi_text="- just a list\n",
        spec_text="> x\n",  # no stories -> at least one violation keeps it invalid
    )
    assert report.documented_status_codes == []


def test_odd_path_and_operation_nodes_are_skipped() -> None:
    """Verify non-dict path items and operations are skipped without error."""
    weird = """openapi: 3.0.3
info:
  title: t
  version: 1.0.0
paths:
  /v1/a: "not a dict"
  /v1/b:
    get: "not a dict"
    post:
      responses:
        '200':
          description: ok
        notacode:
          description: ignored
"""
    report = _core(openapi_text=weird)
    assert report.documented_status_codes == ["200"]


def test_isolation_violation_in_contract_test() -> None:
    """Verify importing private domain code from a contract test is flagged."""
    bad = "from src.modules.shortener_api.domain.engine import DecisionEngine\n"
    report = _core(contract_test_text=CONTRACT_TEST + bad)
    assert report.is_valid is False
    assert any("black-box isolation" in v and "Contract test" in v for v in report.violations)


def test_isolation_violation_in_behavioral_test() -> None:
    """Verify importing private adapters from a behavioral test is flagged."""
    bad = "from src.modules.shortener_api.adapters.firestore import Repo\n"
    report = _core(behavioral_test_text=BEHAVIORAL_TEST + bad)
    assert report.is_valid is False
    assert any("black-box isolation" in v and "Behavioral test" in v for v in report.violations)


def test_isolation_check_noop_without_subsystem() -> None:
    """Verify the isolation check is skipped when no subsystem name is known."""
    bad = "from src.modules.shortener_api.domain.engine import DecisionEngine\n"
    report = _core(subsystem="", contract_test_text=CONTRACT_TEST + bad)
    assert not any("black-box isolation" in v for v in report.violations)


def test_to_dict_exposes_valid_alias() -> None:
    """Verify CoverageAuditReport.to_dict exposes the 'valid' alias."""
    data = _core().to_dict()
    assert data["valid"] is True
    assert data["subsystem"] == "shortener_api"


def _scaffold(tmp_path: Path) -> Path:
    """Create a canonical repo layout under tmp_path and return the openapi.yaml path."""
    module_dir = tmp_path / "src" / "modules" / "shortener_api"
    module_dir.mkdir(parents=True)
    (module_dir / "openapi.yaml").write_text(OPENAPI, encoding="utf-8")
    (module_dir / "SPEC.md").write_text(SPEC, encoding="utf-8")

    contract_dir = tmp_path / "tests" / "contract" / "shortener_api"
    contract_dir.mkdir(parents=True)
    (contract_dir / "test_contract_shortener_api.py").write_text(CONTRACT_TEST, encoding="utf-8")

    behavioral_dir = tmp_path / "tests" / "behavioral" / "shortener_api"
    behavioral_dir.mkdir(parents=True)
    (behavioral_dir / "test_behavioral_shortener_api.py").write_text(
        BEHAVIORAL_TEST, encoding="utf-8"
    )

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "PRD.md").write_text(PRD, encoding="utf-8")

    return module_dir / "openapi.yaml"


def test_audit_subsystem_tests_valid_layout(tmp_path: Path) -> None:
    """Verify the file layer discovers sibling and conventional files and passes."""
    openapi_path = _scaffold(tmp_path)
    report = audit_subsystem_tests(openapi_path)
    assert report.is_valid is True
    assert report.subsystem == "shortener_api"


def test_audit_subsystem_tests_missing_files(tmp_path: Path) -> None:
    """Verify missing test files surface as violations rather than crashing."""
    module_dir = tmp_path / "src" / "modules" / "shortener_api"
    module_dir.mkdir(parents=True)
    (module_dir / "openapi.yaml").write_text(OPENAPI, encoding="utf-8")
    (module_dir / "SPEC.md").write_text(SPEC, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PRD.md").write_text(PRD, encoding="utf-8")

    report = audit_subsystem_tests(module_dir / "openapi.yaml")
    assert report.is_valid is False
    assert any("Contract test suite is missing" in v for v in report.violations)
    assert any("Behavioral test suite is missing" in v for v in report.violations)


def test_audit_subsystem_tests_prd_override(tmp_path: Path) -> None:
    """Verify the --prd override path is honored by the file layer."""
    openapi_path = _scaffold(tmp_path)
    alt_prd = tmp_path / "alternate_prd.md"
    alt_prd.write_text(PRD, encoding="utf-8")
    report = audit_subsystem_tests(openapi_path, prd_path=alt_prd)
    assert report.is_valid is True


def test_main_cli_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify the CLI exits 0 and reports valid on a compliant layout."""
    openapi_path = _scaffold(tmp_path)
    exit_code = main([str(openapi_path)])
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["valid"] is True


def test_main_cli_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify the CLI exits 1 and prints diagnostics when suites are missing."""
    module_dir = tmp_path / "src" / "modules" / "shortener_api"
    module_dir.mkdir(parents=True)
    (module_dir / "openapi.yaml").write_text(OPENAPI, encoding="utf-8")
    (module_dir / "SPEC.md").write_text(SPEC, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PRD.md").write_text(PRD, encoding="utf-8")

    exit_code = main([str(module_dir / "openapi.yaml")])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Test coverage audit failed" in captured.err


def test_main_cli_missing_arg() -> None:
    """Verify the CLI errors when the file argument is omitted."""
    with pytest.raises(SystemExit):
        main([])
