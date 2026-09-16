---
id: GEN-2001
title: "Standalone OSS deployment scope"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-05-10T02:50:04.495685Z
updated_at: 2026-05-10T06:41:00.249935Z
---

# GEN-2001: Standalone OSS deployment scope

## Statement

This repository MUST model one standalone Shifter deployment and avoid cross-install orchestration concepts in the OSS app model.

## Rationale

The OSS user experience should be a direct install-and-run model with one configured backend, rather than exposing concepts that belong to external orchestration systems.

## Traceability

- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- IMPLEMENTS → CODE_FILE `shifter/installation/schema.py` (`installation.schema.RootConfig`, extra=forbid, single-deployment field set (no fleet/registry keys))
- IMPLEMENTS → DOCUMENTATION `shifter/installation/README.md` (installation README, root config models exactly one standalone deployment)
- TESTS → TEST `shifter/installation/tests/test_schema.py` (test_root_models_exactly_one_standalone_deployment / test_cross_install_orchestration_keys_rejected)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#723` (Define root installation config schema)
