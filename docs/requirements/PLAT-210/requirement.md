---
id: PLAT-210
title: "Shifter ACES Compatibility Profile"
status: DRAFT
type: INTERFACE
priority: MUST
wave: 3
created_at: 2026-05-09T05:21:44.772541Z
updated_at: 2026-06-29T02:44:58.682200Z
---

# PLAT-210: Shifter ACES Compatibility Profile

## Statement

Before ACES-backed scenario definitions are enabled for provisioning, Shifter shall document the supported ACES compatibility profile: accepted ACES version or dialect, supported scenario capabilities, unsupported capabilities, Shifter-owned backend responsibilities, and user-facing diagnostics for constructs outside the supported profile. CyberScript compatibility shall be documented as transition/archive support while it remains live, not as a co-equal future DSL profile; additional non-ACES profiles require a later ADR or requirement.

## Rationale

Multiple future-facing DSL profiles would make migration correctness ambiguous and could silently extend legacy semantics. The ACES migration needs one explicit Shifter ACES profile plus clear diagnostics and legacy compatibility notes, while current CyberScript behavior remains operational until parity and cutover are proven.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#676` (PLAT-007: Scenario Expressiveness Dependency)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#620` (Scenario expressiveness gap: cyberscript can't describe polaris-class events, forcing provisioner end-runs)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#314` (Create CyberScript CLI tool and shared validation package)
