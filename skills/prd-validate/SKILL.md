---
name: prd-validate
description: Validates draft Product Requirements Documents (PRDs), extracts business goals, personas, and user stories, audits non-functional requirements against Google Cloud Well-Architected Framework (WAF) pillars, interactively resolves ambiguities, and writes a frozen, authoritative docs/PRD.md. Use when the user submits a draft PRD or requirements prompt, asks to validate or clarify specifications, run an intake assessment, or check requirements readiness before architectural design ("/prd-validate", "validate this PRD", "check requirements completeness", "audit PRD NFRs", "run intake gatekeeper").
---

# Product Intake & WAF Gap Assessment (Gate -1)

## Overview
This skill serves as the **Intake Gatekeeper (Gate -1)** for Maestro. It ingests an initial PRD description or prompt from the user, compares it against the Google Cloud Well-Architected Framework (WAF), conducts an interactive clarification dialogue to resolve gaps and ambiguities, and synthesizes the finalized, frozen **`docs/PRD.md`**.

`docs/PRD.md` acts as the **binding contractual baseline** for all subsequent skills in the pipeline (`/architect-design`, `/secops-audit`, `/lead-decompose`, `/test-architect`, `/prd-to-backlog`), guaranteeing that downstream agents never hallucinate, alter scope, or violate agreed non-functional constraints.

## When to Use
Use when:
- The user provides an initial prompt, feature description, or draft requirements and needs an authoritative PRD.
- The user requests an intake assessment or requirements review (`/prd-validate`, "validate this PRD", "audit our requirements", "check PRD completeness").
- Preparing requirements before invoking the Lead Cloud Architect (`/architect-design`).

Do **not** use for:
- Macro-architectural decomposition or component topology design (use `/architect-design`).
- Security threat modeling or STRIDE audit on existing architecture (use `/secops-audit`).
- Syncing user stories with GitHub Issues / backlog management (use `/prd-to-backlog`).
- Writing application or test code (use `/implement` or `/test-architect`).

## Core Process

### 1. Ingest User Input & WAF Registry
1. Ingest the user's initial PRD description, prompt, or draft specification.
2. Read the canonical WAF registry from `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/resources/waf/gcp_waf.json` across all 7 pillars:
   - System Design
   - Operational Excellence
   - Security, Privacy & Compliance
   - Reliability & Disaster Recovery
   - Cost Optimization
   - Performance Optimization
   - Sustainability
3. For deep assessments or specific workload patterns, reference the live raw Google Cloud Agent Skills listed in `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/resources/waf/gcp_waf.json` (e.g., `https://raw.githubusercontent.com/google/skills/main/skills/cloud/google-cloud-waf-security/SKILL.md`).

### 2. Multi-Dimensional Gap & Feasibility Audit
Evaluate the provided input across five critical dimensions:
1. **Business Justification & Goals**: Is the core business problem clearly stated? Are target metrics and success criteria defined?
2. **User Personas & Use Cases**: Are the actors, permissions, and user journeys explicitly identified?
3. **Functional Requirements (FR)**: Are capabilities unambiguous, testable, and free of vague terminology (e.g., "fast", "scalable", "user-friendly")?
4. **WAF Non-Functional Requirements (NFR)**:
   - *System Design*: Target GCP compute environment (Cloud Run, GKE, Cloud Functions) and regional topology.
   - *Operational Excellence*: Observability requirements (Structured Logging, Cloud Trace, Metrics) and target SLOs (e.g. 99.9% availability).
   - *Security & Privacy*: Authentication mechanism (OAuth2/OIDC, IAM, API Keys), authorization model, data classification, encryption requirements.
   - *Reliability*: Target RTO (Recovery Time Objective), RPO (Recovery Point Objective), retry/idempotency expectations, fault tolerance.
   - *Cost Optimization*: Monthly cloud budget ceilings, scale-to-zero expectations, traffic volume estimations.
   - *Performance*: Expected RPS throughput, P95/P99 latency thresholds, payload sizes.
   - *Sustainability*: Low-carbon GCP region selection preference.
5. **Constraint & Conflict Detection**: Flag unrealistic or conflicting constraints (e.g., multi-region active-active database with sub-10ms global latency and a $50/month budget).

### 3. Interactive Clarification Dialogue
1. If any critical NFRs, business goals, or conflicting constraints are discovered, **prompt the user with targeted multiple-choice or direct questions** before generating the final document.
2. Formulate concrete options with sensible GCP defaults where applicable.
3. Incorporate the user's answers into the final requirement baseline.

### 4. Synthesize and Freeze the Contractual `docs/PRD.md`
1. Reconcile the initial user description with the answers obtained during the clarification step.
2. Structure the finalized document strictly following `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/prd-validate/references/prd-template.md`:
   - **Contract Header**: Status `FROZEN / BINDING CONTRACT`, source, and downstream governance notice.
   - **Section 1**: Executive Summary, Business Goals & KPIs (why the product is being created).
   - **Section 2**: Target Personas & Use Cases (who will use the solution).
   - **Section 3**: Functional Requirements (FR-1, FR-2, ...).
   - **Section 4**: Non-Functional Requirements Matrix (7 WAF Pillars with measurable contractual targets).
   - **Section 5**: Agile User Stories (US-1, US-2, ...) with Given-When-Then Acceptance Criteria linked to the WAF NFR matrix.
   - **Section 6**: Technical Constraints, Assumptions & Out of Scope.
3. Write the resulting document to `docs/PRD.md` in the target project workspace.
4. Present a high-level summary of the frozen PRD to the user, highlighting the verified WAF matrix and user stories.

## Downstream Contract Enforcement
Once frozen, `docs/PRD.md` serves as the contractual baseline for subsequent personas:
- **`/architect-design`**: Must satisfy every FR and NFR in `docs/PRD.md` without introducing unauthorized scope.
- **`/secops-audit`**: Validates that the architecture satisfies the security and compliance requirements in Section 4.
- **`/lead-decompose`**: Authors OpenAPI contracts matching the user stories and acceptance criteria in Section 5.
- **`/test-architect`**: Authors orthogonal test suites derived strictly from the acceptance criteria in Section 5.
- **`/prd-to-backlog`**: Generates GitHub Issues derived directly from Section 5 user stories.

## Red Flags & Common Rationalizations
| Common Pitfall | Reality / Enforcement |
|---|---|
| "The user didn't mention SLOs, so I'll omit the Operational Excellence pillar." | **Never omit pillars.** Always prompt the user or apply standard production SLOs (99.9% uptime, structured logging) with user consent. |
| "I'll write architecture recommendations directly in the PRD." | **Respect separation of concerns.** PRD defines *what* and *why* (requirements, constraints, metrics); `/architect-design` decides *how* (topology, services, patterns). |
| "The draft looks good enough, I'll freeze it without asking clarifying questions." | **Intake is the single cheapest place to fix bugs.** If any NFR is vague, ask the user immediately. |
| "I will generate user stories without acceptance criteria." | Every user story MUST have testable Given-When-Then Acceptance Criteria and link to corresponding WAF NFRs. |

## Verification
The intake validation is complete only when all criteria are satisfied:
- [ ] Business goals, justification, and success KPIs are clearly articulated.
- [ ] Target personas and their core pain points/goals are defined in tabular format.
- [ ] Functional requirements are numbered, testable, and unambiguous.
- [ ] All 7 Google Cloud WAF pillars are explicitly populated in the NFR Matrix with measurable targets.
- [ ] Agile user stories include Given-When-Then Acceptance Criteria (`AC-X.Y`) linked to WAF NFRs.
- [ ] Technical constraints, assumptions, and out-of-scope boundaries are documented.
- [ ] The output file is written to `docs/PRD.md` with the contractual binding header.

## References
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/skills/prd-validate/references/prd-template.md` — Canonical markdown template for `docs/PRD.md`.
- `${MAESTRO_PLUGIN_DIR:-$HOME/.gemini/config/plugins/maestro}/resources/waf/gcp_waf.json` — Google Cloud Well-Architected Framework registry and live skill endpoints.
