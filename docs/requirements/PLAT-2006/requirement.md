---
id: PLAT-2006
title: "AWS/GCP compatibility and security preservation"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-05-10T02:50:04.466069Z
updated_at: 2026-06-13T06:34:24.906309Z
---

# PLAT-2006: AWS/GCP compatibility and security preservation

## Statement

Migration of existing AWS and GCP support MUST preserve current security controls, guardrails, and operational safety unless an ADR records an intentional change.

## Rationale

The re-architecture should improve maintainability without silently weakening deployment security, identity controls, network isolation, or validation coverage.

## Traceability

- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- CONSTRAINS → ADR `ADR-009` (AWS and GCP keep provider-specific identity stacks behind a shared auth seam)
- DOCUMENTS → DOCUMENTATION `docs/architecture/branch-routing-provider-coupling-inventory.md` (Branch Routing and Provider Coupling Inventory)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#724` (Inventory branch routing and provider coupling)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#728` (Migrate AWS support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#729` (Migrate GCP support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#730` (Replace branch-targeted deployment docs and CI routing)
- IMPLEMENTS → GITHUB_ISSUE `140` (Security: RDS IAM authentication and CA certificate)
- IMPLEMENTS → PULL_REQUEST `971` (security: harden rds auth and ca settings)
- IMPLEMENTS → CODE_FILE `platform/terraform/modules/portal/rds/main.tf` (Portal RDS instance CA and IAM auth settings)
- IMPLEMENTS → CODE_FILE `scripts/check_tf_rds_security/check_tf_rds_security.py` (RDS security Terraform guardrail checker)
- IMPLEMENTS → CODE_FILE `platform/terraform/modules/guacamole/rds.tf` (Guacamole RDS instance CA and IAM auth settings)
- TESTS → TEST `scripts/check_tf_rds_security/test_check_tf_rds_security.py` (RDS security checker tests)
- IMPLEMENTS → CONFIG `.pre-commit-config.yaml` (Local RDS security guardrail hook wiring)
- IMPLEMENTS → CONFIG `.github/workflows/_quality.yml` (CI RDS security guardrail wiring)
- IMPLEMENTS → CONFIG `platform/terraform/.checkov.yaml` (Terraform Checkov waiver cleanup)
- IMPLEMENTS → ADR `ADR-004-R12` (RDS security guardrail registry rule)
- DOCUMENTS → GITHUB_ISSUE `954` (Quality trigger routing regression)
- IMPLEMENTS → PULL_REQUEST `978` (ci: tighten quality workflow routing)
- IMPLEMENTS → CONFIG `.github/workflows/deploy.yml` (Deploy workflow Quality routing classifier and PR Gate)
- IMPLEMENTS → ADR `ADR-003-R2` (Deploy workflow plan and Quality routing scope rule)
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (ADR guard tests for Quality routing and PR Gate enforcement)
- DOCUMENTS → DOCUMENTATION `docs/technical/dev/ci-cd.md` (CI/CD documentation for Quality routing)
- DOCUMENTS → DOCUMENTATION `docs/technical/dev/adr-enforcement.md` (ADR enforcement documentation for Quality routing guardrails)
- IMPLEMENTS → CODE_FILE `shifter/installation/registry.py` (installation.registry, AWS backend bundle migrated to a closed settings model, reference-pattern grammars, and the proof profile, preserving controls (#728))
- IMPLEMENTS → CODE_FILE `shifter/installation/loader.py` (installation.loader, splits the shared range_egress key out of the closed AWS settings model, preserving its cross-backend security validation and verbatim CIDR diagnostics (#728))
- TESTS → TEST `shifter/installation/tests/test_registry.py` (Tests: AWS bundle migration, closed settings model, reference patterns, and proof profile (#728))
- TESTS → TEST `shifter/installation/tests/test_loader.py` (Tests: AWS closed-model loader validation, secret reference patterns, proof profile, and range_egress verbatim CIDR errors (#728))
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/deploy_workflow.py` (ADR-003-R2 quality/plan routing guardrail enforcement, check_deploy_workflow_plan_scope)
