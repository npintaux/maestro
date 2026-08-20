---
name: test-architect
description: Independent Test Architect persona that authors orthogonal behavioral acceptance tests and OpenAPI contract verification suites directly from PRD user stories and frozen SPEC.md specifications. Enforces Gate 8 contract compliance and independent semantic correctness without developer bias. Use when creating black-box test suites, writing contract compliance tests, generating behavioral acceptance scenarios from PRD/SPEC, or implementing the independent verification suite ("/test-architect", "author contract tests", "generate behavioral tests", "independent test suite", "verify subsystem against PRD").
---

# Independent Test Architect (Gate 8 & Orthogonal Verification)

## Overview
This skill embodies the **Independent Test Architect** persona for Maestro. Operating with strict separation of concerns from the developer, the Test Architect derives behavioral acceptance suites and contract verification tests **solely from `docs/PRD.md` and `src/modules/<subsystem>/openapi.yaml` / `SPEC.md`**.

### The Core Invariant
> **A developer cannot green-light their own understanding of requirements.**
> Developer-authored TDD unit tests prove internal logic consistency and line coverage. However, only an *orthogonal, independent suite* authored from the specification proves semantic correctness against user intent and protects against requirement misinterpretations.

---

## When to Use
Use when:
- Creating black-box contract verification suites (`tests/contract/<subsystem>/`).
- Creating end-to-end behavioral acceptance suites mapped to PRD User Stories (`tests/behavioral/<subsystem>/`).
- Verifying HTTP status codes, error schemas, header formats, and payload schemas against `openapi.yaml`.
- Authoring test suites for any of the 5 Maestro domain patterns (decision-list, repository-service, state-machine, pipeline-reducer, algorithmic-core).

Do **not** use for:
- Writing developer internal unit tests or mock classes within `src/` (use `/implement`).
- Decomposing subsystems or designing internal class hierarchies (use `/lead-decompose`).
- Authoring or modifying `openapi.yaml` or `SPEC.md` contracts (use `/lead-decompose`).
- Macro cloud architecture or WAF compliance audits (use `/architect-design`).

---

## Core Process

### 1. Ingest Requirements & Contracts
1. Read `docs/PRD.md` to extract:
   - User stories (US-1, US-2, ...) and acceptance criteria (AC-1.1, AC-1.2, ...).
   - Expected error scenarios and non-functional requirements (SLOs, boundary limits).
2. Read `src/modules/<subsystem>/openapi.yaml` to identify:
   - Versioned endpoint paths (`/v1/...`), operations, parameter types, and response schemas.
   - Required HTTP status codes (`2xx`, `400`, `404`, `409`, `422`, `500`).
3. Read `src/modules/<subsystem>/SPEC.md` to identify:
   - Declared domain pattern (`> **Selected Domain Pattern**: <pattern>`).
   - Defined error taxonomy and status code mappings.

### 2. Scaffold Independent Test Directories
Ensure the orthogonal test layout exists outside `src/`:
```
tests/
├── contract/
│   └── <subsystem>/
│       └── test_contract_<subsystem>.py     # Schema & status code conformance
├── behavioral/
│   └── <subsystem>/
│       └── test_behavioral_<subsystem>.py   # User story acceptance scenarios
└── fixtures/
    └── <subsystem>_fixtures.py              # Schema-compliant test data
```

### 3. Author OpenAPI Contract Conformance Suite
Create `tests/contract/<subsystem>/test_contract_<subsystem>.py` conforming to `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/test-architect/references/contract-test-template.py`:
1. **Routing & Versioning**: Assert that all subsystem endpoints start with version prefix `/v<N>/`.
2. **Success Payloads (`200`/`201`)**: Assert response schema contains all required fields with expected types.
3. **Client Validation (`400 Bad Request`)**: Send missing/invalid types and assert structured error payload (`error_code`, `message`).
4. **Missing Resources (`404 Not Found`)**: Request nonexistent entity and verify `ENTITY_NOT_FOUND` error schema.
5. **Business/Lifecycle Violations (`409 Conflict` / `422 Unprocessable`)**: Trigger state conflicts or policy violations and assert error schema.
6. **Fault Isolation (`500 Internal Error`)**: Inject an adapter/datastore fault via an entrypoint dependency override (never by patching internal domain classes) and verify a clean structured `500` with no stack-trace leakage.

Assert conformance against the **frozen** `openapi.yaml` (load and compare), not the app's self-reported `/openapi.json`, so implementation drift from the contract is caught.

### 4. Author Behavioral Acceptance Suite
Create `tests/behavioral/<subsystem>/test_behavioral_<subsystem>.py` conforming to `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/test-architect/references/behavioral-test-template.py`:
1. **Traceability in Test Names**: Every test function must cite its parent PRD User Story and Acceptance Criterion:
   ```python
   def test_us1_ac1_2_malformed_url_rejected_with_validation_error(client: TestClient) -> None:
       """[US-1][AC-1.2] Malformed URLs are rejected with 400 Bad Request."""
   ```
2. **Domain Pattern Specific Focus**:
   - **`decision-list`**: Test each rule predicate boundary, rule short-circuit ordering, and composite allow/deny decisions.
   - **`repository-service`**: Test active entity retrieval, missing entity 404s, and deactivated entity 410/404 handling via in-memory fake repositories.
   - **`state-machine`**: Test the complete legal state transition matrix, assert illegal transitions raise `409 Conflict` (`STATE_CONFLICT`), and verify terminal state immutability.
   - **`pipeline-reducer`**: Test stage transformation sequence, accumulator immutability, and stream aggregation boundary cases.
   - **`algorithmic-core`**: Test known-answer reference cases, edge topologies (single-node, disconnected target), and output determinism.

### 5. Execute Verification & Capture RED-Lock
1. Run the mechanical Gate 8 coverage auditor, which cross-references the frozen specs against your suites (documented status codes → contract assertions; SPEC-claimed PRD User Stories → behavioral references; black-box isolation):
```bash
python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_test_coverage.py" src/modules/<subsystem>/openapi.yaml
```
- Must exit with code `0` and `{"valid": true}`.
- A green pytest run is **not** sufficient: this gate fails a suite that omits a documented status code, skips a claimed User Story, or imports the subsystem's private `domain/`/`adapters/` code.

2. Run the orthogonal test suites to verify they fail cleanly against unimplemented code (the RED state):
```bash
pytest tests/contract/<subsystem>/ -v
pytest tests/behavioral/<subsystem>/ -v
```

3. **Capture the Cryptographic RED-Lock**:
Lock the failing orthogonal test suite before handing off to the Implementer:
```bash
python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/verify_red_suite.py" lock --subsystem <subsystem>
```
- Exits with `0` and creates `.maestro/red_lock/<subsystem>.json` containing SHA256 hashes of all contract and behavioral test files.
- Fails if the suite is already green (exit `1`) or missing (exit `1`).
- Protects the test suite from being tampered with or weakened during developer implementation.

> **Role Isolation Note**: The Test Architect executes with environment variable `MAESTRO_ACTIVE_ROLE=test-author` and `MAESTRO_ACTIVE_SUBSYSTEM=<subsystem>`. The PreToolUse hook boundary guard mechanically blocks all write operations outside `tests/contract/<subsystem>/` and `tests/behavioral/<subsystem>/`.

> **Framework note**: The test templates target FastAPI's `TestClient` against a public `entrypoints/api.py:app`. The web framework is an architectural decision — it must be frozen in `architecture.md` (Gate 0) / `SPEC.md` (Gate 1). If a different framework is frozen, adapt the client fixture accordingly; do not silently introduce one here.

---

## Red Flags & Common Rationalizations
| Common Pitfall | Reality / Enforcement |
|---|---|
| "I'll import private domain classes directly in the contract tests." | **Isolation violation.** Contract tests must treat the subsystem as a black box, interacting only via public entrypoints (`entrypoints/api.py`). |
| "I'll rely on the developer's unit tests to verify PRD acceptance criteria." | **Verification failure.** Developer unit tests are white-box scaffolding. Semantic correctness requires an orthogonal suite. |
| "I'll skip testing 4xx error schemas since the happy path works." | **Mechanical failure.** `audit_test_coverage.py` fails the gate when any status code documented in `openapi.yaml` is not asserted by a contract test. |
| "I won't label tests with US/AC identifiers." | **Mechanical failure.** The coverage auditor requires every PRD User Story claimed in `SPEC.md` to be referenced (`[US-X]`) by a behavioral test. |
| "I'll assert against the app's own `/openapi.json` — it's easier." | **Contract drift.** Conformance must be checked against the frozen `openapi.yaml`; the app's self-report can drift with the implementation. |

---

## Verification
The Independent Test Architect's work is complete only when:
- [ ] `tests/contract/<subsystem>/test_contract_<subsystem>.py` is authored and verifies all endpoints and status codes from `openapi.yaml`.
- [ ] `tests/behavioral/<subsystem>/test_behavioral_<subsystem>.py` is authored and covers all PRD User Stories and Acceptance Criteria.
- [ ] Every behavioral test method explicitly references its `[US-X][AC-X.Y]` traceability identifier.
- [ ] Tests respect the subsystem's declared domain pattern test focus.
- [ ] Tests interact exclusively with public entrypoints or domain ports without importing private classes.
- [ ] `python3 "${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_test_coverage.py" src/modules/<subsystem>/openapi.yaml` exits with code `0` (all documented status codes and claimed User Stories are covered).

---

## References
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/test-architect/references/contract-test-template.py` — Canonical OpenAPI contract test suite.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/test-architect/references/behavioral-test-template.py` — Canonical PRD-traceable behavioral test suite.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/scripts/audit_test_coverage.py` — Mechanical Gate 8 auditor (status-code & User-Story coverage + black-box isolation).
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/lead-decompose/references/patterns/` — Domain pattern specifications and testing focus.
