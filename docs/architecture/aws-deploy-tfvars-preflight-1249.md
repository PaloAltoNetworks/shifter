# AWS Deploy Tfvars Preflight (#1249 / PLAT-005)

Status: pre-implementation guidance

Date: 2026-05-14

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1249>

Requirement: PLAT-005 — Per-Deployment Configuration

## Scope Boundary

This work is deploy-configuration wiring for the existing AWS Terraform
entrypoints. It should make AWS deploy workflows consume deployment-owned
Terraform overrides from GitHub Actions secrets before planning or applying,
matching the repository's `example.com` baseline model. It must not redesign
Terraform modules, migrate state, change runtime app settings, or introduce a
new deployment configuration abstraction.

## Architecture Decisions

- The committed AWS `terraform.tfvars` files remain OSS/example baselines.
  Deployment-owned values belong in gitignored `local.auto.tfvars` files
  rendered in the CI workspace or created locally by an operator.
- The reusable workflow that runs a Terraform root must render that root's
  override file before every `terraform plan` and every `terraform apply`.
  Planning against the baseline and applying against real values is a
  configuration drift bug.
- Use GitHub Actions secrets as the CI source of truth for whole-file AWS
  override payloads unless there is a stronger reason to split a specific value
  into a repository variable. Do not commit real domains, email addresses,
  bucket names, account IDs, public keys, or CIDR allowlists to replace the
  baseline.
- Missing deploy secrets are workflow preflight failures. Error messages should
  name the missing secret and the docs path, never print the secret body or
  rendered tfvars contents.
- Provider-specific roots stay provider-specific. AWS portal/range/core
  workflows should not import GCP renderers or Identity Platform settings, and
  GCP workflows should not become the schema for AWS portal config.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1249 |
| --- | --- | --- |
| Example baseline and local override contract | `platform/terraform/environments/*/**/terraform.tfvars`, `.gitignore`, `docs/dev/deploy-secrets.md` | Keep committed baselines non-operational; render gitignored `local.auto.tfvars` next to each Terraform root that needs deployment-owned values. |
| GCP deploy-time precedent | `.github/workflows/_gcp-dev.yml` `Render local.auto.tfvars from secrets/variables` | Reuse the fail-loud, docs-linked preflight shape, but keep AWS secret names and Terraform roots AWS-local. |
| AWS deploy routing | `.github/workflows/deploy.yml`, `_core.yml`, `_range.yml`, `_shifter-platform.yml`, `_shifter-engine.yml` | Pass required secrets through the caller and render in the reusable workflow that owns the Terraform working directory. |
| Terraform validation | `terraform fmt`, `terraform validate`, `.tflint.hcl`, ADR-004-R7 `no-plaintext-secrets-in-tfvars` | Do not weaken existing Terraform checks; generated overrides stay untracked so ADR-004 continues to guard committed tfvars. |
| Workflow validation | `actionlint`, `.github/workflows/_quality.yml`, `.gc/plan-rules.md` | Workflow edits are guardrail-file edits and must pass `actionlint` plus ADR guard. |
| Secret scanning and generated artifacts | `.gitleaks.toml`, `.gitignore`, ADR-004-R8 | Keep rendered tfvars and plan outputs in the job workspace only; do not upload or comment full override payloads. |

## Cross-Cutting Layers

- Auth surface: GitHub OIDC role assumption remains the AWS auth boundary via
  `aws-actions/configure-aws-credentials`. Tfvars rendering must not choose a
  role, widen role permissions, or add long-lived AWS keys.
- Secret-handling surface: GitHub Actions secrets hold the CI payloads;
  `local.auto.tfvars` is a transient, gitignored workspace file. Shell steps
  must avoid `set -x`, avoid echoing payloads, and avoid passing tfvars content
  through command-line arguments where it can appear in process lists or logs.
- Env-binding shape: the workflow secret names are the external CI binding; the
  generated file is plain Terraform HCL loaded by Terraform's native
  `*.auto.tfvars` precedence. Terraform variable validation remains the shape
  checker for variable names and values.
- Config validators: the change must satisfy `actionlint`, `terraform fmt`,
  `terraform validate`, `tflint`, and ADR guard. If a root has no real
  deployment-owned values, document that explicitly rather than adding an empty
  renderer.
- OS/process exposure: write the secret body to a file with shell redirection
  from an environment variable or stdin inside the job workspace. Do not use
  `terraform -var`, `echo "$SECRET"` for diagnostics, or generated filenames
  outside the Terraform root.
- Error and observability surface: workflow failures should use GitHub Actions
  `::error::` annotations naming the missing secret, target environment, and
  docs path. Plan comments may include Terraform plans as they do today, but
  must not include the rendered override file.

## Extensibility

The seam is the mapping from Terraform root plus environment to the secret that
contains that root's override HCL. Keep it parameterized by workflow input
`environment` and root name, for example `dev`/`prod` plus `portal`, so adding
`range` or `core` deployment-owned overrides later is another mapped secret,
not copied ad hoc shell logic in every job. If repeated rendering logic grows,
factor a small workflow-local shell helper or script only after the second real
AWS root needs identical behavior.

## Whole-Repo View

In-scope artifacts are:

- `.github/workflows/deploy.yml` for passing secrets into reusable workflows.
- `.github/workflows/_shifter-platform.yml` for AWS portal plan/apply
  rendering.
- `.github/workflows/_core.yml` and `.github/workflows/_range.yml` for audit
  and possible equivalent rendering if those roots depend on stripped values.
- `platform/terraform/environments/{dev,prod}/portal/**`,
  `platform/terraform/environments/{dev,prod}/range/**`, and
  `platform/terraform/environments/{dev,prod}/**` for Terraform variable
  contracts and backend files.
- `docs/dev/deploy-secrets.md` for the canonical operator-facing inventory.
- `.gitignore`, `.gitleaks.toml`, `.tflint.hcl`, `.gc/plan-rules.md`, and
  `scripts/adr_guard/adr_guard.py` as enforcement and generated-file
  boundaries.

## Gotchas And Anti-Patterns

- Do not render the override only in `apply`; the plan must see the same
  deployment configuration.
- Do not conflate `domain_name`, `ctfd_domain`, `ses_domain`,
  `ctf_from_email`, `alarm_email`, `allowed_email_domains`, SSH ingress CIDRs,
  and bucket names. They are separate Terraform contracts even if they share a
  deployment domain.
- Do not parse or validate HCL with shell string matching beyond empty-secret
  checks. Terraform owns HCL parsing and variable validation.
- Do not make AWS depend on GCP variables such as `GCP_PUBLIC_HOSTNAME`, or
  collapse AWS and GCP identity/domain settings into a single workflow secret.
- Do not print rendered tfvars, upload it as an artifact, include it in PR
  comments, or write it outside ignored Terraform environment roots.
- Do not broaden ADR guard, gitleaks, or workflow skip filters to get the deploy
  wiring through CI.
- Do not silently fall back to the committed baseline for protected deploys when
  a required secret is missing.

## Non-Goals

- No Terraform module redesign, state migration, resource renaming, bucket
  import, ACM replacement strategy, or DNS automation.
- No runtime Django settings refactor, provider selector change, or startup
  validation implementation.
- No new secret store abstraction, schema registry, exception hierarchy,
  logging framework, or deploy orchestration framework.
- No change to GCP Helm/bootstrap contracts beyond using them as precedent.
