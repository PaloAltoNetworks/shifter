---
id: PLAT-208
title: "Database Maintenance-Window Safety"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-05-09T05:11:30.315057Z
updated_at: 2026-05-09T05:11:30.327734Z
---

# PLAT-208: Database Maintenance-Window Safety

## Statement

Production database infrastructure changes shall default to maintenance-window application, while non-production deployments may opt into immediate application. Deployment automation shall fail clearly when accepted database changes remain pending after apply so operators do not mistake queued maintenance changes for live capacity or state changes.

## Rationale

The RDS module and CI now distinguish dev/prod database apply behavior and verify pending modifications after apply. This is an operational reliability requirement discovered from live deployment behavior.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#703` (RDS module: apply_immediately defaults to false, queues changes for maintenance window)
- IMPLEMENTS → CONFIG `platform/terraform/modules/portal/rds/main.tf` (RDS apply_immediately input and maintenance-window default)
- IMPLEMENTS → CONFIG `platform/terraform/modules/portal/rds/variables.tf` (RDS apply_immediately variable contract)
- IMPLEMENTS → CODE_FILE `scripts/check_rds_pending_modifications/check_rds_pending_modifications.py` (RDS pending modification CI checker)
- IMPLEMENTS → CONFIG `.github/workflows/_shifter-platform.yml` (Deploy workflow RDS pending-modification gate)
- TESTS → TEST `scripts/check_rds_pending_modifications/tests/test_check_rds_pending_modifications.py` (RDS pending-modification checker tests)
- IMPLEMENTS → PULL_REQUEST `1090` (RDS module apply_immediately maintenance-window merge)
