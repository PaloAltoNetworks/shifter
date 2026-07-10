# Identifier Hygiene Preflight (#936)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/936>

## Scope Boundary

This workstream removes deployment-owned cloud identifiers from tracked
operational tooling and adds a repo-native guard against reintroduction. It is
security hygiene, not a new deploy configuration system.

The issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Architecture Decisions

- Committed Terraform and Packer variable files are examples or
  non-operational baselines. Real AWS account IDs, VPC IDs, subnet IDs, backend
  buckets, bake buckets, and account-suffixed storage buckets belong in
  deployment-owned overlays or workflow inputs/secrets.
- Reuse the existing `TF_VARS_<ENV>_*` / gitignored `local.auto.tfvars`
  contract for Terraform roots. Do not invent a second per-environment schema
  for account-bound values.
- Packer should keep its existing Packer-native variable file contract.
  Deployment-specific Packer values should be supplied from an untracked var
  file or a deploy-time rendered var file, not from committed live IDs.
- Polaris bake/support tooling is operational tooling. Its account-bound S3
  bucket, S3 URI, subnet, and Secrets Manager ARN examples must become
  placeholders, environment variables, workflow inputs, or ignored local files,
  with the same fail-loud behavior as existing deploy-secret rendering.
- Identifier hygiene belongs in existing enforcement. Prefer extending
  `scripts/adr_guard/adr_guard.py` under ADR-004 over adding a disconnected
  scanner. Gitleaks remains the entropy/secret scanner; the new check is for
  low-entropy but sensitive infrastructure identifiers.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #936 |
| --- | --- | --- |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/README.md`, `.pre-commit-config.yaml`, `.github/workflows/_quality.yml` | Add the hygiene check to ADR guard, fast + CI levels, tests, pre-commit scope, and ADR-004 docs. |
| Terraform deployment overlays | `_range.yml`, `_shifter-platform.yml`, `docs/dev/deploy-secrets.md`, `platform/terraform/environments/*/**/local.auto.tfvars.example` | Use `TF_VARS_<ENV>_*` or gitignored `local.auto.tfvars`; never commit account-local IDs to baseline tfvars. |
| Root deploy config | `shifter/installation/schema.py`, `contract.py`, `registry.py`, `range_egress.py` | Keep `shifter.yaml` as the source for backend settings it already owns; do not add a parallel YAML parser for this cleanup. |
| Workflow validation | `actionlint`, ADR-003 deploy-workflow checks, self-hosted runner gating | Workflow input/default changes must preserve trusted-event gating and fail-loud missing-value messages. |
| Secret/identifier scanning | `.gitleaks.toml`, ADR-004-R7/R8/R9, new ADR-004 identifier rule | Do not broaden allowlists. Fixed synthetic examples are allowed only as explicit test/documentation sentinels. |
| Polaris operator scripts | `scripts/polaris-aws-range/common.py`, `.gitignore`, `polaris-scenario-bake.yml` input validation | Centralize default region/profile behavior in existing helpers; keep account-bound bake inputs outside tracked defaults. |
| Packer validation | `shifter/packer/variables.pkr.hcl`, `shifter/packer/tests/test_packer.py`, `packer.yml` | Preserve Packer's required-variable validation and structured CLI args; render or pass real values at build time. |

## Cross-Cutting Layers

- Auth surface: GitHub OIDC remains the AWS credential boundary. This cleanup
  must not add static AWS keys, widen role assumptions, or make privileged
  self-hosted jobs reachable from pull requests.
- Secret-handling surface: identifiers are not secret values, but they are
  reconnaissance-sensitive operational data. Real values must be supplied from
  GitHub secrets/variables, workflow inputs validated by strict regexes, local
  ignored overlays, SSM/Secrets Manager references, or operator environment
  variables. Do not print full secret payloads or rendered var files.
- Env-binding shape: Terraform roots consume HCL through native `.tfvars` /
  `*.auto.tfvars` precedence; Packer consumes `.pkrvars.hcl`; Polaris scripts
  consume environment variables and existing helper defaults. Let each native
  parser validate its own shape.
- Config validators: changes must pass ADR guard, actionlint for workflows,
  Terraform fmt/validate/TFLint where Terraform is touched, Packer tests where
  Packer files are touched, and the repo-wide identifier scan. Validation
  messages should name path, line, and identifier kind, not echo live values.
- OS/process exposure: write secret or identifier payloads to files through
  environment variables/stdin/redirection inside the job workspace. Avoid
  `-var value=<secret-or-identifier-payload>` for multi-value payloads, `set -x`,
  and shell string interpolation of untrusted workflow inputs.
- Error/log surface: fail loud on missing required deploy inputs with
  `::error::` annotations and a docs pointer. Do not include account IDs,
  bucket names, VPC IDs, subnet IDs, ARNs, or full tfvars payloads in logs.

## Extensibility

The seam is a centralized tracked-file identifier policy: token patterns,
fixed synthetic allowlist, placeholder allowlist, scoped path exceptions, and
diagnostic redaction all live in one ADR guard check. The next identifier family
such as AMI IDs, ECR account URLs, or provider project IDs should be another
case in that policy, not a second script or ad hoc `grep` job.

Region selection is a separate parameter seam. Keep defaults where they are
documented compatibility defaults, but workflow/Packer/Polaris paths that block
multi-instance or multi-region operation should read a single environment,
workflow input, or variable value instead of hardcoding `us-east-2` in multiple
places.

## Whole-Repo View

In-scope artifacts include:

- `platform/terraform/global/github-runner/**` for runner VPC/subnet/backend
  configuration and documentation.
- `shifter/packer/**` and `.github/workflows/packer*.yml` for AMI bake
  variable binding and region/account assumptions.
- `scripts/polaris-aws-range/**` and `.github/workflows/polaris-scenario-bake.yml`
  for bake buckets, S3 URIs, subnet defaults, Secrets Manager ARN examples, and
  region/profile helper behavior.
- `platform/terraform/environments/{dev,prod}/range/**`,
  `platform/terraform/environments/{dev,prod}/portal/**`, and
  `docs/dev/deploy-secrets.md` for the existing baseline/overlay contract.
- `scripts/adr_guard/**`, `docs/adr/**`, `.pre-commit-config.yaml`,
  `.github/workflows/_quality.yml`, and `.gitleaks.toml` for enforcement.
- `.gitignore` and scoped local `.gitignore` files for generated or operator
  override files.

## Gotchas And Anti-Patterns

- Do not replace live identifiers with new PANW/customer/account-specific
  identifiers. Use placeholders, examples, or deploy-time overlays.
- Do not conflate secret values with identifiers. Gitleaks is still required,
  but account IDs, VPC IDs, subnet IDs, and bucket names need deterministic
  policy checks because they are low entropy.
- Do not make `<...>` a universal placeholder pattern. Use a small fixed
  placeholder set or explicit synthetic examples so a real value cannot be
  hidden inside brackets.
- Do not scan only the three files named in the issue. Acceptance is repo-wide
  for tracked files, with deliberate exclusions only for fixed synthetic test
  fixtures and non-live documentation examples.
- Do not treat Terraform, Packer, and Polaris as one schema. They share the
  security rule, but each tool owns its native variable format and validation.
- Do not broaden workflow path filters, runner gates, gitleaks allowlists, or
  ADR exceptions to land the cleanup.
- Do not upload rendered var files, Terraform plans, Packer manifests, Polaris
  provisioning state, or local operator overlays as artifacts unless a separate
  policy explicitly permits sanitized evidence.

## Non-Goals

- No git history rewrite, account migration, bucket import, Terraform state
  migration, runner recreation, AMI promotion, or live deploy.
- No new root deployment schema, secret-store abstraction, exception hierarchy,
  logging framework, or scanner framework.
- No weakening of ADR guard, Checkov, TFLint, actionlint, Packer validation,
  gitleaks, or workflow runner exposure controls.
- No broad region-provider redesign beyond parameterizing places this issue
  must touch to remove identifier-coupled hardcodes.
