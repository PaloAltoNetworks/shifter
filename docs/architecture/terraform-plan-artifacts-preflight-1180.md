# Terraform Plan Artifact Hygiene Preflight (#1180)

Status: pre-implementation guidance

Date: 2026-05-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1180>

## Scope Boundary

Terraform plan files are generated security-sensitive outputs, not source
contracts. This issue is repository hygiene and guardrail hardening: remove
tracked plan outputs, ignore future local plan outputs, and add a lightweight
repo check that rejects staged Terraform plan artifacts under environment
trees. It must not change Terraform modules, backend state, deploy semantics,
or CI plan behavior except to keep plan files out of committed source.

The issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Architecture Decisions

- Treat Terraform binary plans and rendered text plans as generated artifacts.
  They may include state-derived values, provider metadata, resource addresses,
  and deployment-specific operational details.
- The canonical source-control boundary is the repository ignore and guardrail
  layer, not provider-specific Terraform modules. Ignore rules should cover
  `tfplan`, `plan.out`, and obvious equivalent plan-output names only under
  Terraform environment trees so source files are not hidden broadly.
- The canonical enforcement seam is the existing architecture/security gate:
  `.pre-commit-config.yaml`, `.github/workflows/_quality.yml`, and
  `scripts/adr_guard/adr_guard.py`. Add a narrow repo-native check there if a
  simple filename/path policy is enough; do not introduce a new scanner
  framework.
- CI may continue generating plan files in job workspaces for comments or
  artifact upload. Those outputs must remain ephemeral CI workspace or CI
  artifact-storage data, not committed files.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1180 |
| --- | --- | --- |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/README.md`, `.pre-commit-config.yaml`, `_quality.yml` | Add any new path policy to the existing ADR guard and document it as an ADR-004 stack-appropriate security guardrail. |
| Terraform source boundary | `.gitignore`, `platform/terraform/environments/**`, `platform/terraform/gcp/environments/**`, `.tflint.hcl` | Ignore local/generated plan outputs without weakening Terraform fmt/validate/TFLint. |
| Secret and sensitive-output scanning | `.gitleaks.toml`, `_quality.yml` `secrets-gitleaks`, ADR-004-R7 `no-plaintext-secrets-in-tfvars` | Keep gitleaks and tfvars checks as backstops, but do not rely on them to understand Terraform binary plan files. |
| Workflow plan generation | `.github/workflows/_shifter-platform.yml`, `.github/workflows/_range.yml`, `.github/workflows/_gcp-dev.yml`, `scripts/bootstrap/deploy.py` | Preserve existing job-local `terraform plan -out=...` behavior unless changing workflow artifact handling directly. |
| Guardrail documentation | `docs/adr/README.md`, `docs/adr/index.yaml`, `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md` | Guardrail-file edits must update ADR enforcement docs in the same change under ADR-002. |

## Cross-Cutting Layers

- Security validators: staged-source protection must pass gitleaks, ADR guard,
  and the new plan-artifact policy. The new policy should be path/name based
  and fail closed for files under Terraform environment roots; gitleaks remains
  a secret scanner, not the primary detector for binary plans.
- Config shapes: `.gitignore` owns local generated-file exclusion; ADR
  registry entries own named enforced checks; pre-commit hook `files:` patterns
  decide which staged paths run fast checks. Keep these shapes consistent so
  local and CI enforcement see the same Terraform environment trees.
- OS/process exposure: no new checker should run `terraform show` on staged
  plans or print plan contents. Diagnostics should report only repo-relative
  paths and remediation.
- Error envelopes and observability: failures should be developer-facing
  guardrail errors naming the blocked path. Do not echo binary payloads,
  rendered plan bodies, provider metadata, resource addresses, or state-derived
  values.
- Auth surface: unchanged. The work should not touch cloud credentials,
  Terraform backends, OIDC roles, or deploy permissions.

## Extensibility

The seam is the blocked path/name set. Keep it centralized in the guardrail
implementation so adding another generated plan filename, provider-specific
environment root, or CI-only exception does not require editing multiple hooks.
The initial roots should cover AWS and GCP environment trees:
`platform/terraform/environments/**` and
`platform/terraform/gcp/environments/**`.

## Gotchas And Anti-Patterns

- Do not add a broad `*.out` ignore at repo root; that can hide unrelated source
  or test fixtures.
- Do not rely on `.gitignore` alone. Already tracked files ignore ignore rules,
  and staged files can still bypass local habits without a guardrail.
- Do not parse binary plans, run Terraform against staged plans, or print plan
  text in guardrail output.
- Do not conflate Terraform state, tfvars, plan files, lockfiles, and generated
  Kubernetes/env files. They have different source-control contracts.
- Do not weaken `.gitleaks.toml`, ADR-004-R7 tfvars checks, TFLint, actionlint,
  or workflow architecture gates to keep the cleanup small.
- Do not remove CI plan comments or artifact uploads merely because local plan
  files are disallowed. The boundary is committed source versus ephemeral CI
  output.

## Non-Goals

- No Terraform module, backend, provider-version, state, lockfile, workspace, or
  deployment workflow redesign.
- No git-history rewrite or secret-rotation work unless a separate incident
  process determines a leaked plan contained live sensitive material.
- No new abstraction, schema, service, exception hierarchy, logging framework,
  or security-scanner framework.
- No changes to runtime application behavior, authentication, Kubernetes
  deployment, or cloud resource topology.
