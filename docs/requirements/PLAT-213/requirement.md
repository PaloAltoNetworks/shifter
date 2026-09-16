---
id: PLAT-213
title: "Experiment Metrics and Benchmarking"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-09T06:03:34.438147Z
updated_at: 2026-05-09T06:03:34.438147Z
---

# PLAT-213: Experiment Metrics and Benchmarking

## Statement

The platform shall support benchmark-oriented experiment analysis across scenario runs, including success criteria evaluation, time-to-objective or step-count metrics where applicable, cross-run comparison, regression detection against prior baselines, and exportable summaries suitable for review or research reporting.

## Rationale

Shifter experiments should not stop at orchestration. LilRAE (formerly APTL) requirements identify benchmark suites, attack-side metrics, stealth scoring, and cross-run comparison as separate capabilities needed to turn runs into evaluable results.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#399` (Experiment management / orchestration tracking)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#466` (Experiment run orchestration tracking)
- DOCUMENTS → SPEC `aptl:BEN-001` (LilRAE specification, former APTL identifier BEN-001: Benchmark Suite)
- DOCUMENTS → SPEC `aptl:BEN-002` (LilRAE specification, former APTL identifier BEN-002: Attack-Side Performance Metrics)
- DOCUMENTS → SPEC `aptl:BEN-003` (LilRAE specification, former APTL identifier BEN-003: Cross-Run Comparison Engine)
- DOCUMENTS → SPEC `aptl:BEN-006` (LilRAE specification, former APTL identifier BEN-006: Stealth Scoring (Dual-Axis Offense + Detection Metrics))
- DOCUMENTS → SPEC `aptl:EXP-007` (LilRAE specification, former APTL identifier EXP-007: Statistical Analysis Pipeline for Experiment Results)
- DOCUMENTS → PULL_REQUEST `780` (Experiment orchestration implementation PR)
