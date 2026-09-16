---
id: PLAT-209
title: "ACES Scenario Definition Migration Path"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 3
created_at: 2026-05-09T05:21:44.748107Z
updated_at: 2026-06-29T02:44:49.181294Z
---

# PLAT-209: ACES Scenario Definition Migration Path

## Statement

The platform shall converge scenario definitions on ACES as the canonical authored scenario contract through a parity-gated migration path. Shifter may maintain CyberScript compatibility during transition and may keep legacy definitions operational until cutover, but new scenario authoring capabilities shall not require authors to extend or rewrite into another non-ACES DSL unless a later ADR or requirement explicitly adds that supported surface.

## Rationale

ADR-024 establishes ACES as the target scenario, runtime, experiment, and backend contract family while preserving current Shifter behavior until parity gates pass. The previous multi-DSL wording made CyberScript, aces, and RQWG look like co-equal future authoring surfaces; the migration direction is now ACES canonical with legacy compatibility only where needed for transition and archive.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#676` (PLAT-007: Scenario Expressiveness Dependency)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#620` (Scenario expressiveness gap: cyberscript can't describe polaris-class events, forcing provisioner end-runs)
