---
id: PLAT-007
title: "Scenario Expressiveness Gap Tracking"
status: ACTIVE
type: CONSTRAINT
priority: SHOULD
wave: 3
created_at: 2026-04-16T22:48:15.828998Z
updated_at: 2026-07-26T02:15:23.166938Z
---

# PLAT-007: Scenario Expressiveness Gap Tracking

## Statement

Shifter shall treat scenario-specific provisioner or runtime end-runs as ACES migration/profile gaps, not as private implementation behavior or new CyberScript semantics. Until ACES parity and cutover gates pass, current CyberScript and CMS scenario paths remain authoritative for production use; new scenario capabilities outside the current CyberScript vocabulary shall be recorded in the ACES migration parity inventory or ACES SDL/profile backlog before the workaround is relied on for event or range production use.

## Rationale

Polaris exposed gaps where the declarative scenario surface could not represent multi-container hosts, per-flag network gating, and per-range agentic-tool configuration. ADR-024 now defines ACES as the target contract family while preserving current Shifter behavior until parity is proven, so expressiveness gaps should route to ACES migration/profile work instead of extending CyberScript indefinitely.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#620` (Scenario expressiveness gap: cyberscript can't describe polaris-class events, forcing provisioner end-runs)
- IMPLEMENTS → POLICY `docs/architecture/aces-migration-parity-inventory.yaml` (ACES parity inventory: governance block (record-before-production-reliance) and the three PLAT-007 expressiveness-gap rows)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/adr_guard.py` (aces-parity-inventory-row-schema check (ADR-024-R2): closed-set category/surface/next_issue_kind, required fields, unique row ids)
- IMPLEMENTS → ADR `docs/adr/index.yaml` (ADR-024-R2 wired to the aces-parity-inventory-row-schema check)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/aces-cyberscript-issue-triage.md` (PLAT-007 requirement posture, pointing at the parity inventory governance block)
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (AcesParityInventoryRowSchemaTests: closed-set membership, required fields, duplicate ids, shrunken required_fields header, and the five fail-closed structural branches)
- DOCUMENTS → DOCUMENTATION `docs/architecture/scenario-expressiveness-gap-tracking-preflight-676.md` (Scenario expressiveness gap tracking architecture preflight (#676))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#676` (PLAT-007: Scenario Expressiveness Gap Tracking)
