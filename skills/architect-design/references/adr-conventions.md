# Architecture Decision Record (ADR) Conventions

## Purpose
Architecture Decision Records (ADRs) capture critical, architecturally significant decisions made during system design and evolution. In Maestro's autonomous swarm pipeline, ADRs serve as the immutable, authoritative justification for decisions, preventing downstream subagents from making contradictory assumptions or re-litigating resolved trade-offs.

## File Placement & Naming
* **Directory**: `docs/adr/` (workspace root relative).
* **Filename pattern**: `XXXX-short-kebab-case-title.md` (e.g. `0001-firestore-for-state-storage.md`, `0002-modular-monolith-topology.md`).
* **Numbering**: Strictly monotonic 4-digit integers starting from `0001`.

## Required Sections & MADR Format
Every ADR must include:
1. **Title**: `# [ADR-XXXX] Title`
2. **Metadata Header**:
   - `* **Status**: proposed | accepted | superseded`
   - `* **Deciders**: ...`
   - `* **Date**: YYYY-MM-DD`
   - `* **Superseded by**: ...` (If superseded, must reference `ADR-YYYY`)
   - `* **Approved-by**: ...` (Sign-off identity/token for Gate 0.5)
3. **Context and Problem Statement**: 2-4 sentences defining the tension/challenge.
4. **Decision Drivers**: Explicit list referencing PRD NFRs (e.g., latency, budget, compliance).
5. **Considered Options**: At least 2 candidate options with pros/cons.
6. **Decision Outcome**: The selected option with explicit WAF rationale, positive consequences, and negative trade-offs.
7. **Pros and Cons of the Options**: Concrete trade-off matrix.
8. **Links & References**: Links to official documentation and related ADRs.

## The Gate 0 & Gate 0.5 Lifecycle
1. **Gate 0 (Macro-Architecture & ADR Check)**:
   - Run `python3 scripts/audit_waf_compliance.py docs/architecture.md`
   - Run `python3 scripts/validate_adrs.py docs/adr/ --architecture docs/architecture.md`
   - All proposed/accepted ADRs must be syntactically valid and trace to the *Frozen Cloud Service Decisions* table in `architecture.md`.
2. **Gate 0.5 (Human Sign-Off Checkpoint)**:
   - Run `python3 scripts/validate_adrs.py docs/adr/ --require-approval`
   - Before Gate 1 (Tier-2 Micro-Decomposition) unlocks, all active ADRs must have `Status: accepted` and a valid `Approved-by:` sign-off token.
