# Subsystem Specification: [Subsystem Name] (`src/modules/[subsystem_name]/`)

> **Status**: `FROZEN / SPEC-DRIVEN DEVELOPMENT BASELINE (Gate 1)`  
> **Source**: Subsystem Tech Lead (`/lead-decompose`)  
> **Parent Architecture**: [`architecture.md`](file:///home/user/orchestrated-coding/architecture.md)  
> **Business Requirements**: [`docs/PRD.md`](file:///home/user/orchestrated-coding/docs/PRD.md)  
> **Interface Contract**: [`openapi.yaml`](file:///home/user/orchestrated-coding/src/modules/[subsystem_name]/openapi.yaml)  
> **Selected Domain Pattern**: `[decision-list | repository-service | state-machine | pipeline-reducer | algorithmic-core]`  
> **Target Implementer**: Developer Worker (`/implement`)  
> **Target Verifier**: Independent Test Architect (`/test-architect`)

---

## 1. Domain Scope & Responsibility
* **Subsystem Identifier**: `[subsystem_name]`
* **Directory Root**: `src/modules/[subsystem_name]/`
* **Domain Purpose**: [Describe domain boundaries and core capabilities]
* **Allowed Dependencies**: [List allowed GCP services and external packages]
* **Encapsulation Rules**: Only public entrypoints in `src/modules/[subsystem_name]/entrypoints/` may be invoked by outside callers. Internal domain models and logic in `src/domain/` are strictly private to this subsystem.

---

## 2. External Contract & API Schema
* **Interface Definition**: Defined in `src/modules/[subsystem_name]/openapi.yaml`.
* **Primary Endpoints**:
  | HTTP Verb | Path | Operation ID | Success Status | Error Statuses |
  |---|---|---|---|---|
  | `POST` | `/v1/[resource]` | `[createResource]` | `201 Created` | `400 Bad Request`, `422 Unprocessable`, `500 Internal Error` |
  | `GET` | `/v1/[resource]/{id}` | `[getResource]` | `200 OK` | `404 Not Found`, `500 Internal Error` |

---

## 3. Domain Models & Data Structures
Immutable dataclasses representing requests, domain entities, and results (see pattern definition in `references/patterns/`):

```python
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SubsystemRequest:
    """Immutable input payload for subsystem processing."""

    request_id: str
    entity_id: str
    amount_cents: int
```

---

## 4. Domain Pattern Realization & Business Logic
*(Refer to the matching template in `references/patterns/<pattern-name>.md`)*

### Selected Pattern: `[e.g. decision-list, repository-service, state-machine, pipeline-reducer, algorithmic-core]`
* **Port / Abstract Base Class**: Defined in `src/domain/[rules/base.py | repository.py | state_machine.py | stages/base.py | solver.py]`
* **Component Breakdown**:
  | Component ID | Class Name | Target File | PRD User Story & AC | Logic & Conditions |
  |---|---|---|---|---|
  | **C1** | `ValidateInputRule` / `LookupService` | `src/domain/...` | US-1 (AC-1.1) | Core domain logic description |
  | **C2** | `CalculateDiscountStage` / `StateTransition` | `src/domain/...` | US-1 (AC-1.2) | Core domain logic description |

---

## 5. Composite Engine / Coordinator (`engine.py` / `service.py` / `pipeline.py`)
* **Coordinator File**: `src/modules/[subsystem_name]/domain/[engine.py | service.py | pipeline.py | state_machine.py | solver.py]`
* **Composition Pattern**: Instantiates and coordinates the domain components.
* **Execution Semantics**: Ordered evaluation, short-circuit on error, state transition dispatch, or transformation pipeline.

---

## 6. Error Taxonomy & Status Code Mapping
| Exception Class | HTTP Status Code | Response Code String | Trigger Scenario |
|---|---|---|---|
| `ValidationError` | `400 Bad Request` | `INVALID_PAYLOAD` | Missing required fields or negative numeric values |
| `EntityNotFoundError` | `404 Not Found` | `ENTITY_NOT_FOUND` | Requested entity ID does not exist in datastore |
| `BusinessRuleViolation` | `422 Unprocessable` | `RULE_VIOLATION` | Domain rule failed on a well-formed request |
| `InvalidTransitionError` | `409 Conflict` | `STATE_CONFLICT` | Event conflicts with the entity's current lifecycle state (state-machine only) |
| `InternalServiceError` | `500 Server Error` | `INTERNAL_ERROR` | Unexpected unhandled exception |

---

## 7. Acceptance Criteria & Test Cases for Verification
The Independent Test Architect (`/test-architect`) must implement orthogonal contract tests verifying:
1. **Scenario 1 (Happy Path)**: Valid request produces expected success response (e.g. `200 OK` or `201 Created`).
2. **Scenario 2 (Validation Failure)**: Invalid payload produces `400 Bad Request` with structured error details.
3. **Scenario 3 (Domain / State / Rule Violation)**: Invalid condition produces `422 Unprocessable` citing the domain violation.
4. **Scenario 4 (Server / Datastore Error)**: Adapter failure produces `500 Internal Error` without leaking stack traces.
