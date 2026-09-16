---
id: PLAT-216
title: "Range Readiness and Prerequisite Validation"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-05-09T06:03:34.492977Z
updated_at: 2026-05-09T06:03:34.492977Z
---

# PLAT-216: Range Readiness and Prerequisite Validation

## Statement

Before launching a participant range, experiment run, or event-specific scenario asset, the platform shall verify that required capacity, cloud/provider resources, credentials, scenario prerequisites, supported DSL capabilities, and referenced artifacts are available. Failed readiness checks shall block launch and report actionable diagnostics rather than allowing a predictable provisioning failure.

## Rationale

LilRAE (formerly APTL) treats system preflight, scenario prerequisite validation, and clean-state guarantees as explicit requirements. Shifter already has capacity-aware provisioning and DSL compatibility work; this requirement ties those checks to the launch boundary.

## Traceability

- DOCUMENTS → SPEC `aptl:INF-007` (LilRAE specification, former APTL identifier INF-007: Pre-Flight System Requirements Check)
- DOCUMENTS → SPEC `aptl:SCN-009` (LilRAE specification, former APTL identifier SCN-009: Scenario Prerequisite Validation)
- DOCUMENTS → SPEC `aptl:RNG-001` (LilRAE specification, former APTL identifier RNG-001: Ephemeral Environments with Clean State Guarantees)
- DOCUMENTS → DOCUMENTATION `scenario-dev/polaris/lessons-3.md` (Polaris lessons: provisioning and egress readiness)
- DOCUMENTS → DOCUMENTATION `scenario-dev/polaris/lessons-4.md` (Polaris lessons: smoke tests and readiness regressions)
