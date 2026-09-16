---
id: GEN-002
title: "Executable Architecture Governance"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-05-09T05:11:30.016736Z
updated_at: 2026-05-09T05:11:30.051524Z
---

# GEN-002: Executable Architecture Governance

## Statement

The repository shall maintain executable architecture governance for accepted architecture constraints. Accepted ADRs with enforceable impact shall be represented in a machine-readable registry, time-bounded exceptions, and automated checks that run locally and in CI; workflow or test skip mechanisms shall not bypass architecture conformance.

## Rationale

The repo now has guardrail enforcement in ADR registry, adr_guard, CI, hooks, and agent policy. This is a governance NFR, not implementation guidance for feature delivery.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1583` (In-tenant artifact preparation and dependency compatibility)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/preparation_policy.py` (Executable preparation Job authority and exact-image admission)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/preparation_installation_readback.py` (Fail-closed verification of installed Kubernetes authority)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/cloud/preparation_cloud_readback.py` (Independent installed cloud IAM and isolation verification)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_preparation_installation_readback.py` (Reject unapproved execution, RBAC, network policy and unconverged installations)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_preparation_cloud_readback.py` (Reject cloud authority and network drift)
- TESTS → TEST `shifter/shifter_platform/tests/shared/cloud/test_preparation_runtime.py` (Exact worker image, identity, command and Secret-backed transport policy)
- TESTS → TEST `shifter/shifter_platform/tests/engine/services/test_preparation_postgres.py` (Real concurrent request serialization, idempotency and capacity across grant versions)
- DOCUMENTS → DOCUMENTATION `docs/ops/artifact-preparation.md` (Operator installation and enforced responsibility boundaries)
- IMPLEMENTS → CODE_FILE `scripts/check_tf_gcp_iam_resource_scope/check_tf_gcp_iam_resource_scope.py` (Closed dynamic-secret name and participant-version conditions verified in the tenant)
- TESTS → TEST `scripts/check_tf_gcp_iam_resource_scope/test_check_tf_gcp_iam_resource_scope.py` (Reject widened prefixes, participant classes, permissions and invalid condition compositions)

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#689` (Refactor CI and guardrail automation god files)
- CONSTRAINS → ADR `ADR-001` (Cross-layer access goes through service boundaries)
- CONSTRAINS → ADR `ADR-002` (Guardrail changes must remain documented)
- CONSTRAINS → ADR `ADR-003` (ADR enforcement is a required architecture gate)
- CONSTRAINS → ADR `ADR-004` (Use stack-appropriate off-the-shelf policy tooling where it fits)
- CONSTRAINS → ADR `ADR-006` (Kubernetes workloads must meet Pod Security Standards)
- CONSTRAINS → ADR `ADR-032` (`raes-plan-accessor-boundary/v1` structurally pins the cross-process RAES plan-reader decision from #1937)
- IMPLEMENTS → CONFIG `docs/adr/index.yaml` (Machine-readable ADR registry)
- IMPLEMENTS → CONFIG `docs/adr/exceptions.yaml` (Time-bounded ADR exceptions)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/adr_guard.py` (ADR guard architecture policy runner)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/adr_registry.py` (Typed accepted-ADR interface-contract validator)
- IMPLEMENTS → CONFIG `.gc/plan-rules.md` (Ground Control plan rules for architecture checks)
- IMPLEMENTS → CONFIG `.github/workflows/_quality.yml` (CI architecture and quality gate)
- IMPLEMENTS → CONFIG `.github/workflows/codeql-analysis.yml` (Blocking CodeQL analysis and upload gate)
- IMPLEMENTS → CONFIG `.github/dependabot.yml` (Update ownership for every Python package root)
- IMPLEMENTS → CONFIG `.pre-commit-config.yaml` (Local guardrail pre-commit hooks)
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (ADR guard regression tests)
- DOCUMENTS → DOCUMENTATION `docs/adr/README.md` (ADR enforcement documentation)
- DOCUMENTS → DOCUMENTATION `docs/adr-enforcement-plan.md` (ADR enforcement design plan)
- IMPLEMENTS → PULL_REQUEST `947` (ADR enforcement audit and guardrail backfill)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#915` (deploy: single source of truth for deployment mode and portal sizing)
- IMPLEMENTS → CONFIG `.github/workflows/_shifter-platform.yml` (AWS portal deploy workflow topology enforcement)
- IMPLEMENTS → CODE_FILE `scripts/portal_deploy/portal_deploy.py` (Terraform-sourced portal deploy topology helper)
- TESTS → TEST `scripts/portal_deploy/tests/test_portal_deploy.py` (Portal deploy topology and ASG verification tests)
- IMPLEMENTS → PULL_REQUEST `964` (fix: unify portal deploy mode source)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#927` (test: adopt a boundary-mock policy + lint to stop topology-coupled tests)
- IMPLEMENTS → PULL_REQUEST `973` (test: add boundary mock policy guard)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/boundary_mock_baseline.json` (Boundary mock legacy baseline)
- CONSTRAINS → ADR `ADR-019` (Tests mock external boundaries, not first-party topology)
- DOCUMENTS → DOCUMENTATION `docs/technical/dev/adr-enforcement.md` (Developer ADR enforcement documentation)
- DOCUMENTS → DOCUMENTATION `docs/architecture/raes-provisioning-plan-accessor-boundary-preflight-1937.md` (Accepted RAES accessor-boundary decision and compatibility handoff to #2082)
- IMPLEMENTS → CODE_FILE `scripts/quality_ownership/contract.py` (Production-path quality-ownership contract parser (#1530))
- IMPLEMENTS → CODE_FILE `scripts/quality_ownership/classify_paths.py` (Fail-closed changed-path classifier for the _quality.yml paths job (#1530))
- IMPLEMENTS → CONFIG `.github/quality-path-filters.yaml` (Versioned production-path quality-ownership contract (#1530))
- TESTS → TEST `scripts/adr_guard/tests/test_quality_path_ownership.py` (Quality-path-ownership gate tests (#1530))
- IMPLEMENTS → GITHUB_ISSUE `1530` (REV1 Testing: enforce production-path ownership in routed CI)
- TESTS → TEST `scripts/adr_guard/tests/test_deploy_workflow.py` (Sonar, dependency, exact-image, secret handling, and release-security workflow invariants)
- IMPLEMENTS → CODE `scripts/gcp/verify_running_image_ids.py` (exact repository-and-digest verification for every running release container)
- TESTS → TEST `scripts/gcp/tests/test_verify_running_image_ids.py` (missing, lookalike, and partial-rollout regression coverage)
- IMPLEMENTS → CODE_FILE `scripts/check_tf_gcp_wif_trust/check_tf_gcp_wif_trust.py` (Purpose-specific GCP CI role-boundary guard)
- TESTS → TEST `scripts/check_tf_gcp_wif_trust/test_check_tf_gcp_wif_trust.py` (Purpose-specific GCP CI role-boundary regression tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2084` (GCP exact-release security gate reconciliation)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/documentation.py` (`lilrae-identity-boundary` check enforcing ADR-024-R6 identity and scenario-pack terminology)
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (LilraeIdentityBoundaryTests for rename continuity, TechVault role, false pairing, and historical evidence boundaries)
- IMPLEMENTS → CONFIG `.github/workflows/iam-drift-check.yml` (Out-of-band global/iam CI drift-check gating on `terraform plan -detailed-exitcode` (ADR-004-R26, #247))
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/_deploy_workflow_iam_drift.py` (`global-iam-drift-check` guard pinning the global/iam drift-check workflow (ADR-004-R26, #247))
- TESTS → TEST `scripts/adr_guard/tests/test_global_iam_drift.py` (global/iam drift-check guard regression tests (#247))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#247` (Audit and scope down OIDC IAM permissions)
