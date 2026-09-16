---
id: GEN-2004
title: "Terraform deploy plan/apply integrity"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-06-12T09:11:45.057786Z
updated_at: 2026-06-12T23:13:51.078031Z
---

# GEN-2004: Terraform deploy plan/apply integrity

## Statement

AWS deploy workflows MUST queue environment-branch apply runs instead of cancelling an in-flight apply, MUST wait on Terraform backend locks for both plan and apply operations, and MUST apply the exact local saved Terraform plan generated in the apply job so safety checks and executed changes cannot diverge without uploading raw binary plan artifacts.

## Rationale

Terraform applies mutate cloud infrastructure and state. Cancelling an in-flight apply or applying without a saved plan can create partially applied infrastructure, stale locks, and TOCTOU drift between safety checks and execution. Raw binary plan artifacts can expose unredacted plan/state data, so the integrity contract uses local saved plans inside the apply job rather than artifact handoff.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `917` (deploy: Terraform plan/apply integrity and concurrency safety)
- IMPLEMENTS → CONFIG `.github/workflows/deploy.yml` (AWS deploy workflow dispatcher)
- IMPLEMENTS → CONFIG `.github/workflows/_core.yml` (Core Terraform deploy workflow)
- IMPLEMENTS → CONFIG `.github/workflows/_range.yml` (Range Terraform deploy workflow)
- IMPLEMENTS → CONFIG `.github/workflows/_shifter-platform.yml` (Shifter platform Terraform deploy workflow)
- IMPLEMENTS → POLICY `scripts/adr_guard/adr_guard.py` (ADR guard deploy workflow integrity rule)
- IMPLEMENTS → ADR `docs/adr/index.yaml` (ADR registry Terraform deploy integrity rule)
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (ADR guard deploy workflow integrity tests)
- DOCUMENTS → DOCUMENTATION `docs/technical/dev/ci-cd.md` (CI/CD Terraform deploy integrity documentation)
- DOCUMENTS → DOCUMENTATION `docs/technical/dev/adr-enforcement.md` (ADR enforcement Terraform deploy integrity documentation)
