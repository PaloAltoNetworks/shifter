---
id: PLAT-005
title: "Per-Deployment Configuration"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-03-19T02:57:49.001248Z
updated_at: 2026-05-09T05:11:30.464493Z
---

# PLAT-005: Per-Deployment Configuration

## Statement

Each deployment shall be configurable for: target cloud provider (AWS or GCP), cloud region, cloud credentials and service accounts, domain name, resource limits and quotas, and environment-specific settings. All deployment configuration shall be externalized from application code and manageable through environment variables, configuration files, or a secret management service. The application shall validate its configuration at startup and fail fast with clear error messages if required configuration is missing or invalid.

## Rationale

Externalized, per-deployment configuration is what makes the same application code deployable across different cloud providers, regions, and organizations. Hard-coded or baked-in configuration creates deployment-specific forks that diverge over time. Fail-fast validation prevents silent misconfiguration from causing runtime failures that are harder to diagnose.

## Traceability

- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py` (Django settings - env vars used but no cloud provider selector, hardcoded AWS SES region, no startup validation for cloud config)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/.env.example` (.env.example - AWS-specific env vars (AWS_S3_BUCKET_NAME, AWS_REGION, ECS ARNs), no GCP equivalents)
- DOCUMENTS → ADR `ADR-007` (GCP control-plane deployments are Helm-packaged and bootstrap-managed)
- DOCUMENTS → ADR `ADR-008` (GCP bootstrap fails closed and uses private operator access)
- DOCUMENTS → POLICY `docs/adr/index.yaml` (ADR registry - GCP Helm cutover and secure bootstrap decisions)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/manual-deployment.md` (Manual deployment runbook - secure GCP bootstrap prerequisites)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/dev/setup.md` (Developer setup - secure GCP bootstrap path)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md` (Secrets documentation - secure GCP portal/OIDC prerequisites)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/dev/terraform.md` (Terraform patterns - GCP secure tfvars and Helm deployment model)
- DOCUMENTS → ADR `ADR-009` (AWS and GCP keep provider-specific identity stacks behind a shared auth seam)
- IMPLEMENTS → CONFIG `platform/charts/shifter/templates/configmap-runtime.yaml` (Runtime configuration ConfigMap template)
- IMPLEMENTS → CODE_FILE `scripts/gcp/render_runtime_env.py` (Generated runtime configuration renderer)
- IMPLEMENTS → CODE_FILE `scripts/bootstrap/deploy.py` (Bootstrap validation and generated deployment values)
- CONSTRAINS → ADR `ADR-007` (GCP control-plane deployments are Helm-packaged and bootstrap-managed)
- CONSTRAINS → ADR `ADR-008` (GCP bootstrap fails closed and uses private operator access)
- IMPLEMENTS → CONFIG `.github/workflows/_shifter-platform.yml` (AWS platform deploy workflow, renders per-deployment local.auto.tfvars from secrets before terraform plan/apply)
- IMPLEMENTS → CONFIG `.github/workflows/deploy.yml` (Deploy entrypoint, passes TF_VARS_DEV_PORTAL / TF_VARS_PROD_PORTAL secrets into the platform workflow)
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (PlatformRendersDeployTfvarsTests, verifies the AWS platform jobs render local.auto.tfvars before terraform runs)
- IMPLEMENTS → ADR `ADR-011` (ADR-011-R7, AWS deploy workflows render deployment-owned tfvars from secrets; committed tfvars stay example baselines)
- DOCUMENTS → DOCUMENTATION `docs/dev/deploy-secrets.md` (Deploy secrets / repository variables, AWS portal section documents TF_VARS_&lt;ENV&gt;_PORTAL and the CI render step)
- DOCUMENTS → DOCUMENTATION `docs/architecture/aws-deploy-tfvars-preflight-1249.md` (Architecture preflight note for #1249, AWS deploy tfvars render design boundary and guardrails)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#674` (PLAT-005: Per-Deployment Configuration)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#784` (ci: AWS platform deploy applies the example.com baseline instead of real per-deployment tfvars)
- IMPLEMENTS → CONFIG `.github/workflows/_shifter-engine.yml` (Engine deploy workflow, fails fast with a clear error when the required ECS task-definition family is missing; gated first_deploy per-deployment bootstrap input)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/deploy_workflow.py` (adr_guard check aws-platform-renders-deploy-tfvars (ADR-011-R7), check_platform_renders_deploy_tfvars)
- IMPLEMENTS → CODE_FILE `scripts/check_tf_gcp_wif_trust/_resolved_plan.py` (Resolved identity trust and impersonation verification)
- IMPLEMENTS → CONFIG `platform/terraform/gcp/modules/cicd-oidc-identity/main.tf` (Generic per-deployment purpose identities in one deployment project)
- TESTS → TEST `scripts/check_tf_gcp_wif_trust/test_resolved_plan.py` (Rejected trust widening, unknown authority, missing bindings and identity replacement)
- TESTS → TEST `platform/terraform/gcp/global/cicd-oidc/tests/inventory.tftest.hcl` (Native unseen-deployment and first-plan purpose coverage)
