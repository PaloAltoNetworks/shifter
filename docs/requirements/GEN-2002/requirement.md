---
id: GEN-2002
title: "Backend-aware setup and validation UX"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 1
created_at: 2026-05-10T02:50:04.520464Z
updated_at: 2026-05-10T06:41:01.335244Z
---

# GEN-2002: Backend-aware setup and validation UX

## Statement

Users SHOULD be able to initialize, configure, and validate their selected backend before applying infrastructure or starting the application.

## Rationale

A backend-aware setup and doctor flow gives OSS users actionable feedback before cloud resources or runtime services are changed.

## Traceability

- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- IMPLEMENTS → CODE_FILE `shifter/installation/cli.py` (installation.cli, shifter-config validate (root config validation before apply/startup))
- IMPLEMENTS → CODE_FILE `shifter/installation/loader.py` (installation.loader.validate_root_config_file, fail-fast validation before Terraform/Helm/Django/deploy)
- IMPLEMENTS → DOCUMENTATION `shifter/installation/README.md` (installation README, how to author and validate shifter.yaml)
- TESTS → TEST `shifter/installation/tests/test_cli.py` (Tests for the shifter-config validate CLI (exit codes, output, python -m installation entry))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#727` (Add backend-aware setup and doctor validation UX)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#730` (Replace branch-targeted deployment docs and CI routing)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#731` (Define initial local backend scope)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#723` (Define root installation config schema)
