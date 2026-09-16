---
id: PLAT-211
title: "Scenario DSL Semantic Validation"
status: DRAFT
type: INTERFACE
priority: MUST
wave: 3
created_at: 2026-05-09T06:03:34.378181Z
updated_at: 2026-05-09T06:03:34.378181Z
---

# PLAT-211: Scenario DSL Semantic Validation

## Statement

The platform shall validate supported scenario DSL definitions before they can be used for provisioning, experiments, or event asset deployment. Validation shall cover the selected DSL compatibility profile, required topology declarations, cross-reference integrity, capability support, and scenario prerequisites, and shall return actionable diagnostics without silently ignoring unsupported constructs.

## Rationale

LilRAE (formerly APTL) separates structural parsing from semantic scenario correctness. Shifter now supports a multi-DSL direction, so compatibility profiles alone are not enough; each CyberScript, aces, or RQWG input needs a pre-provisioning validity contract.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#620` (Scenario expressiveness gap: cyberscript can't describe polaris-class events)
- DOCUMENTS → SPEC `aptl:DSL-001` (LilRAE specification, former APTL identifier DSL-001: Formal Scenario Specification Language)
- DOCUMENTS → SPEC `aptl:DSL-008` (LilRAE specification, former APTL identifier DSL-008: Infrastructure Topology Declaration in Scenario DSL)
- DOCUMENTS → SPEC `aptl:SCN-009` (LilRAE specification, former APTL identifier SCN-009: Scenario Prerequisite Validation)
