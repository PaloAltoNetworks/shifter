---
id: PLAT-212
title: "Experiment Protocol and Run Evidence"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-05-09T06:03:34.419782Z
updated_at: 2026-05-09T06:03:34.419782Z
---

# PLAT-212: Experiment Protocol and Run Evidence

## Statement

The platform shall support a declarative experiment protocol that records the scenario, DSL identity, experimental conditions, run count, timeout policy, success criteria, assigned script or prompt, and any condition-specific configuration. Each experiment run shall produce durable run evidence including the resolved protocol, lifecycle events, artifacts captured during execution, result summary, and enough metadata to reproduce or audit the run.

## Rationale

PLAT-205 covers experiment orchestration at a product-capability level. LilRAE (formerly APTL) adds the missing research-grade contract: runs must be specified and archived in a way that supports repeatability, audit, and comparison.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#399` (Experiment management / orchestration tracking)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#466` (Experiment run orchestration tracking)
- DOCUMENTS → SPEC `aptl:SCN-008` (LilRAE specification, former APTL identifier SCN-008: Append-Only Event Timeline)
- DOCUMENTS → SPEC `aptl:EXP-002` (LilRAE specification, former APTL identifier EXP-002: Experiment Protocol Specification)
- DOCUMENTS → SPEC `aptl:EXP-009` (LilRAE specification, former APTL identifier EXP-009: Structured Experiment Result Summary Export)
- DOCUMENTS → SPEC `aptl:REP-001` (LilRAE specification, former APTL identifier REP-001: Experiment Manifest for Reproducibility)
- DOCUMENTS → SPEC `aptl:SCN-006` (LilRAE specification, former APTL identifier SCN-006: Run Archive Packaging and S3 Export)
- DOCUMENTS → PULL_REQUEST `780` (Experiment orchestration implementation PR)
