---
id: PLAT-2005
title: "Backend-derived runtime configuration"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-05-10T02:50:04.408765Z
updated_at: 2026-07-13T06:43:48.468298Z
---

# PLAT-2005: Backend-derived runtime configuration

## Statement

Django, workers, and provisioner processes MUST derive provider and capability adapter selection from validated backend configuration.

## Rationale

Runtime behavior should follow the same installation contract users configure and should not depend on branch routing or scattered provider environment assumptions.

## Traceability

- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- CONSTRAINS → ADR `ADR-009` (AWS and GCP keep provider-specific identity stacks behind a shared auth seam)
- DOCUMENTS → DOCUMENTATION `docs/architecture/branch-routing-provider-coupling-inventory.md` (Branch Routing and Provider Coupling Inventory)
- DOCUMENTS → CODE_FILE `shifter/installation/contract.py` (installation.contract, names the per-backend runtime outputs (GeneratedOutput with process roles) and the backend discovery path that backend-derived runtime config (#1114) will consume)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#724` (Inventory branch routing and provider coupling)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#725` (Define backend bundle contract and registry)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#728` (Migrate AWS support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#729` (Migrate GCP support into a backend bundle)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/_runtime_env.py` (Django runtime env: derives provider + capability adapter selection from validated backend config)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/_cloud.py` (Django cloud config: provider + capability adapter selection from validated backend config)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/__init__.py` (Shared cloud adapter factory: provider + capability adapter selection from validated backend config)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/config/_gcp_backend.py` (Provisioner config: selects the validated GCP range backend)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/config/_gce.py` (Provisioner config: derives GCE capability behavior from validated backend configuration)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/cloud/__init__.py` (Provisioner cloud adapter factory: provider + capability adapter selection from validated backend config)
- IMPLEMENTS → CODE_FILE `shifter/installation/render.py` (Installation render: derives provider + capability adapter selection from validated backend config into generated outputs)
- TESTS → TEST `shifter/shifter_platform/tests/config/test_runtime_env.py` (Tests: Django runtime env provider/capability adapter derivation)
- TESTS → TEST `shifter/shifter_platform/tests/config/test_settings.py` (Tests: Django settings backend-derived config)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_factory.py` (Tests: shared cloud adapter factory selection)
- TESTS → TEST `shifter/engine/provisioner/tests/test_config.py` (Tests: provisioner config provider/capability derivation)
- TESTS → TEST `shifter/engine/provisioner/tests/cloud/test_factory.py` (Tests: provisioner cloud adapter factory selection)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#726` (Derive runtime configuration from selected backend bundle)
