---
id: PLAT-2001
title: "Root installation configuration"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-05-10T02:49:54.839808Z
updated_at: 2026-05-10T06:40:58.620773Z
---

# PLAT-2001: Root installation configuration

## Statement

Shifter MUST have one authoritative root installation configuration that selects the backend bundle and supplies deployment-level settings used to derive runtime, infrastructure, and validation behavior.

## Rationale

An OSS installation should be configured from a single contract rather than scattered provider files, branch names, and environment-specific assumptions.

## Traceability

- TESTS → TEST `shifter/installation/tests/test_runtime_inventory.py` (Tests for runtime inventory validation and CLI output)
- TESTS → TEST `scripts/gcp/tests/test_render_runtime_env.py` (GCP runtime renderer tests tied to runtime inventory key contract)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#763` (Inventory runtime configuration surfaces and add validation gate)
- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- DOCUMENTS → DOCUMENTATION `docs/architecture/branch-routing-provider-coupling-inventory.md` (Branch Routing and Provider Coupling Inventory)
- IMPLEMENTS → CODE_FILE `shifter/installation/schema.py` (installation.schema, root config typed schema (RootConfig, DeploymentConfig))
- IMPLEMENTS → CODE_FILE `shifter/installation/loader.py` (installation.loader, load + fail-fast validate the root config)
- IMPLEMENTS → CODE_FILE `shifter/installation/errors.py` (installation.errors, ConfigIssue / InstallationConfigError)
- IMPLEMENTS → DOCUMENTATION `shifter/installation/README.md` (installation package README, shifter.yaml contract and field reference)
- IMPLEMENTS → CONFIG `shifter/installation/examples/aws.yaml` (Example root installation config, AWS backend)
- IMPLEMENTS → CONFIG `shifter/installation/examples/gcp.yaml` (Example root installation config, GCP backend)
- TESTS → TEST `shifter/installation/tests/test_schema.py` (Tests for installation.schema (root config validation))
- TESTS → TEST `shifter/installation/tests/test_loader.py` (Tests for installation.loader (file load + fail-fast validation))
- TESTS → TEST `shifter/installation/tests/test_errors.py` (Tests for installation.errors (error model; no input leakage))
- TESTS → TEST `shifter/installation/tests/test_examples.py` (Tests that the shipped example configs validate against the same parser)
- IMPLEMENTS → CODE_FILE `shifter/installation/registry.py` (installation.registry, known backends / allowed profiles for the root config (supersedes the deleted installation.backends))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#724` (Inventory branch routing and provider coupling)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#726` (Derive runtime configuration from selected backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#727` (Add backend-aware setup and doctor validation UX)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#730` (Replace branch-targeted deployment docs and CI routing)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#723` (Define root installation config schema)
- IMPLEMENTS → CODE_FILE `shifter/installation/runtime_inventory.py` (installation.runtime_inventory, sanitized runtime config surface inventory and key-only validation)
- IMPLEMENTS → CODE_FILE `shifter/installation/cli.py` (installation.cli, shifter-config runtime-inventory command)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-configured backend bundles, runtime inventory validation boundary)
