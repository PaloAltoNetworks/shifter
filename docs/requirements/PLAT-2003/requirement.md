---
id: PLAT-2003
title: "Backend bundle contract"
status: ACTIVE
type: INTERFACE
priority: MUST
wave: 1
created_at: 2026-05-10T02:49:54.968536Z
updated_at: 2026-05-10T17:32:20.324243Z
---

# PLAT-2003: Backend bundle contract

## Statement

Each backend bundle MUST expose a stable machine-readable contract for required settings, generated outputs, infrastructure entrypoints, validation checks, health checks, and documentation.

## Rationale

A backend contract lets Shifter add and validate backends without spreading provider-specific behavior across branch routing, scripts, workflows, and runtime settings.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#726` (Derive runtime configuration from selected backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#727` (Add backend-aware setup and doctor validation UX)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#728` (Migrate AWS support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#729` (Migrate GCP support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#731` (Define initial local backend scope)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#725` (Define backend bundle contract and registry)
- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- IMPLEMENTS → CODE_FILE `shifter/installation/contract.py` (installation.contract, BackendBundle and the typed contract parts (settings_model, generated_outputs, validation_checks, health_checks, capabilities, owned_files, docs))
- IMPLEMENTS → CODE_FILE `shifter/installation/registry.py` (installation.registry, BACKEND_BUNDLES: provisional aws/gcp bundles instantiating the contract)
- IMPLEMENTS → CODE_FILE `shifter/installation/loader.py` (installation.loader, runs the selected backend bundle's settings/secret-reference checks against the contract)
- TESTS → TEST `shifter/installation/tests/test_contract.py` (tests for installation.contract, contract model validation, settings_issues, secret_reference_issues, sensitivity/destination rules)
- TESTS → TEST `shifter/installation/tests/test_registry.py` (tests for installation.registry, bundle well-formedness, derived constants, generated-output / capability / owned-files invariants)
- TESTS → TEST `shifter/installation/tests/test_loader.py` (tests for installation.loader, backend-specific settings/secret validation, aggregated path-anchored issues)
- IMPLEMENTS → CODE_FILE `shifter/installation/settings_gcp.py` (installation.settings_gcp, closed GcpBackendSettings model (project_id/region) completing the GCP bundle contract (#729))
- TESTS → TEST `shifter/installation/tests/test_gcp_bundle.py` (tests for the completed GCP bundle, secret reference grammar, generated-output classification + runtime_inventory agreement, published settings-schema constraints, validation checks (#729))
- TESTS → TEST `shifter/installation/tests/test_settings_gcp.py` (tests for the closed GcpBackendSettings model, project_id/region grammar, extra=forbid, loader integration (#729))
