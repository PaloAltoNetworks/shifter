---
id: PLAT-2004
title: "Branch-independent deployment targeting"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-05-10T02:49:54.998621Z
updated_at: 2026-07-14T05:56:36.147080Z
---

# PLAT-2004: Branch-independent deployment targeting

## Statement

Deployment target selection MUST come from explicit configuration or invocation, not from repository branch names.

## Rationale

Branch-targeted deployment is confusing for OSS users and makes backend expansion harder to maintain safely.

## Traceability

- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- DOCUMENTS → DOCUMENTATION `docs/architecture/branch-routing-provider-coupling-inventory.md` (Branch Routing and Provider Coupling Inventory)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#724` (Inventory branch routing and provider coupling)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#730` (Replace branch-targeted deployment docs and CI routing)
- IMPLEMENTS → CODE_FILE `.github/workflows/deploy.yml` (Manual workflow_dispatch deploy with environment input (#730))
- TESTS → TEST `scripts/adr_guard/tests/test_deploy_workflow.py` (TestManualDeployDispatch: push/PR never deploy; environment input selects target)
