# GCP CI/CD And Packer Preflight (#505)

Status: pre-implementation guidance

Date: 2026-06-23

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/505>

Issue title: PLAT-001.10: CI/CD + Packer for GCP

This note records architecture guardrails for adding GCP deployment paths,
GCE-image Packer builds, GCP-specific CI/CD configuration, and MCP ops tooling
support. It is not an implementation plan.

## Scope Boundary

This work should extend the existing provider-specific deployment and image
build surfaces without changing AWS behavior. GCP control-plane deployment,
GCP/GDC guest-image lifecycle, control-plane container images, and AWS AMIs are
separate concepts and must stay separate in names, docs, storage, and workflow
inputs.

No new ADR is required before implementation if the work stays inside the
existing decisions below. Add or revise an ADR only if the implementation
changes the canonical image metadata source of truth, changes deploy branch
trust/routing, adds a new privileged MCP class, weakens GCP bootstrap security,
or introduces a new cross-provider deployment abstraction.

## Architecture Decisions

- GCP deploy automation must build on the current `deploy.yml` →
  `_gcp-dev.yml` route: trusted push/workflow_dispatch only for self-hosted
  mutation, GitHub Environment binding, Workload Identity Federation, generated
  `local.auto.tfvars`, Terraform apply, Artifact Registry push, generated
  runtime env, generated edge manifests, and rollout/certificate verification.
- GCE image baking should extend the existing `shifter/packer` and Packer
  workflow conventions, but provider-specific builders and variables must stay
  provider-scoped. Do not turn AWS AMI variables, SSM parameter names, or
  promotion semantics into a generic image schema by renaming them in place.
- GCP image references must be consumed by the GCP/GDC runtime contracts that
  already exist. VM Runtime guest images flow through `GDC_*_IMAGE_URL` /
  `GDC_VM_IMAGE_GCS_SECRET_ID` and `_gdc_vm_image_source.py`; control-plane
  containers flow through `artifact_registry_image_roots` and immutable tags.
  If Compute Engine guest-image consumers are added, keep their image refs in a
  GCP-specific provisioner/config seam rather than `/shifter/ami/*`.
- MCP ops support must reuse the existing policy-gated GitHub workflow bridge
  (`build_ami` / `promote_ami`, `buildGhWorkflowRunArgs`, `ghExec`) and the
  `registerTool` policy layer. New GCP image/deploy tools are `infra_mutation`
  unless they are strictly read-only diagnostics.
- The implementation must keep the current docs honest. In particular,
  `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/ami-management.md`
  currently says GCP does not use Packer; once #505 lands, that section must be
  revised rather than left as stale operator guidance.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #505 |
| --- | --- | --- |
| Deploy orchestration and trust routing | `.github/workflows/deploy.yml`, `.github/workflows/_gcp-dev.yml`, ADR-003-R5 | Keep PRs on hosted validation only. Any job that assumes cloud credentials, pushes images, mutates infra, or restarts runtimes stays gated to trusted push/workflow_dispatch with a GitHub Environment. |
| GCP CI auth | `google-github-actions/auth` in `_gcp-dev.yml`, `GCP_SERVICE_ACCOUNT`, `GCP_WORKLOAD_IDENTITY_PROVIDER` | Use WIF/OIDC. Do not add long-lived service account keys to GitHub secrets, Packer vars, process argv, artifacts, or repo files. |
| Deploy-time config | `_gcp-dev.yml` `Render local.auto.tfvars from secrets/variables`, `gcp-dev-destroy.yml` mirror render, `docs/dev/deploy-secrets.md` | Missing values fail loud with `::error::`; generated tfvars stay in the CI workspace and are not uploaded or printed. |
| GCP Terraform | `platform/terraform/gcp/**`, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, ADR-004-R11 | Reuse module variables/outputs and validation. New Checkov skips need ADR exceptions; do not soft-fail Terraform Checkov. |
| GCP runtime renderers | `scripts/gcp/render_runtime_env.py`, `render_edge_manifest.py`, `render_private_service_netpol.py` | Keep production runtime fail-closed: no `latest`, no HTTP/ingress-IP fallback, no Redis secret in ConfigMaps, no broad private-service egress. |
| GCP/GDC guest image contract | `platform/k8s/gcp/overlays/*/platform-runtime.env`, `config.GDCVMRuntimeConfig`, `_gdc_vm_image_source.py`, `_gdc_vm_secrets.py` | Use existing logical guest roles and URL schemes. Image-import credentials are Secret Manager payloads surfaced as Kubernetes secrets, not committed values. |
| Packer build surface | `shifter/packer/*.pkr.hcl`, `shifter/packer/tests/test_packer.py`, `.github/workflows/packer.yml` | Extend tests and validation for the GCE builder without breaking AWS `amazon-ebs` templates, var files, manifests, or SSM updates. |
| MCP ops | `mcp/ops/index.js`, `mcp/ops/lib.js`, `mcp/ops/policy.js`, `.shifter.yaml`, `mcp/ops/tool-surface.test.js` | Register tools through `registerTool`; use argv arrays for `gh`/cloud CLIs; update surface tests and apex rules when adding prod-impacting tools. |
| Architecture gates | `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.pre-commit-config.yaml`, `.github/workflows/_quality.yml` | Workflow, guardrail, Terraform, K8s, MCP, and Packer changes must keep their stack-native checks wired. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- GitHub Actions auth and runner exposure: deploy/image-build mutation jobs must
  request the minimum token permissions, use cloud OIDC, and stay off
  `pull_request`. The `deploy-workflow-runner-exposure` ADR check must still
  evaluate pull-request paths as fail-closed.
- Secret handling: GitHub secrets may hold CI binding values, but secret bodies
  must be written by redirection or tool stdin to ephemeral files only when a
  target tool requires a file. Do not echo generated tfvars, service account
  payloads, Packer credentials, Secret Manager payloads, or image-import keys.
- Env-binding shapes: GCP deployment settings flow through `_gcp-dev.yml`
  secrets/vars and Terraform validation; GDC guest image settings flow through
  the existing `GDC_*` env contract; MCP policy settings flow through
  `.shifter.yaml`. Do not duplicate these schemas in workflow shell.
- Config validators: `terraform fmt`, `terraform validate`, TFLint with the
  Google plugin, blocking Terraform Checkov, `packer validate`, Packer tests,
  actionlint, ADR guard, kube-linter/kubeconform, and MCP lint/tests all remain
  authoritative on their surfaces.
- OS/process exposure: do not pass secrets in command-line flags where they can
  appear in process lists. Prefer existing argv-array helpers and temp files
  with cleanup for large or secret payloads. Avoid `set -x` in workflows.
- Error and observability surface: workflow errors should name the missing
  binding, environment, and docs path, not payload values. MCP errors and audit
  records must use the existing sanitization/redaction behavior.

Maintainability incumbents the implementation must build on:

- Use `_gcp-dev.yml` as the GCP deploy shape and `gcp-dev-destroy.yml` as the
  mirror for auth/config rendering, not a parallel GCP deploy framework.
- Use `scripts/bootstrap/deploy.py` helpers as the local/bootstrap precedent
  for argv validation, redacted logs, image tag validation, GDC image-secret
  sync, and Helm/runtime rendering.
- Use `shifter/packer` for image bake templates/tests and keep AWS workflow
  semantics stable.
- Use `mcp/ops` GitHub workflow helpers for agent-triggered workflow runs
  instead of spawning `gh` directly from a new tool.

Extensibility seam:

The seam is `(provider, environment, logical_image_type, immutable_ref)`, not a
template filename or provider-neutral "machine image" blob. Keep workflow
inputs and helper constants parameterized so adding `gcp-prod`, another GCP
region, or a new logical guest image is a mapping/data change rather than a new
workflow copy. If repeated Packer build logic grows across AWS and GCP, factor
only the common workflow mechanics; do not factor provider storage, promotion,
or consumer contracts together prematurely.

Whole-repo surfaces in scope:

- `.github/workflows/deploy.yml`, `_gcp-dev.yml`, `gcp-dev-destroy.yml`,
  `packer.yml`, `packer-promote.yml`, and `_quality.yml`.
- `.github/quality-path-filters.yaml` when new GCP Packer/MCP paths need
  targeted Quality coverage.
- `shifter/packer/**` for templates, variables, scripts, tests, and manifests.
- `platform/terraform/gcp/**`, `platform/k8s/gcp/**`,
  `platform/charts/shifter/**`, and `scripts/gcp/**`.
- `scripts/bootstrap/deploy.py` only if local/bootstrap image or deploy
  workflows need equivalent behavior.
- `mcp/ops/**`, `mcp/shared/**`, `.shifter.yaml`, and
  `mcp/ops/SECURITY.md` if MCP commands are added.
- `docs/adr/**`, `docs/dev/deploy-secrets.md`, and platform infrastructure
  docs when guardrails, secrets, or image lifecycle docs change.

## Gotchas And Anti-Patterns

- Do not call GCE images "AMIs" in GCP code, workflow inputs, docs, MCP tool
  names, or Terraform variables except when explicitly describing the AWS
  legacy path.
- Do not store GCE image refs in AWS SSM `/shifter/ami/*`, and do not make AWS
  provisioner code depend on GCP image variables.
- Do not make `_gcp-dev.yml` run long-running guest image bakes on every
  control-plane deploy unless the deployment truly consumes a newly baked image
  and the image reference is immutable.
- Do not reuse AWS Packer `vpc_id`, `subnet_id`, `aws_region`, AMI promotion,
  or SSM update logic for GCP. Use GCP-specific project, zone/region, network,
  service account, image family/name, labels, and output contracts.
- Do not add a new MCP policy class for GCP command support unless the existing
  `infra_mutation` / `observability` classes cannot express the risk.
- Do not create another CLI execution helper that accepts shell strings.
  Extend existing argv-array helpers or add provider-specific argv builders
  with tests.
- Do not commit real GCP project IDs, bucket names, service account emails,
  private CIDRs, image-import credentials, or workstation/admin allowlists
  unless an ADR exception explicitly covers the path.
- Do not weaken ADR guard, actionlint, Checkov, TFLint, kube validators, Packer
  tests, or MCP surface tests to get the CI/CD change through.

## Non-Goals

- No redesign of the root backend-bundle model, deploy branch model, or
  provider selection.
- No AWS AMI workflow behavior change beyond compatibility-preserving extension.
- No Terraform state migration, GKE topology redesign, Identity Platform
  redesign, or Kubernetes runtime security relaxation.
- No new cloud adapter exception hierarchy, logging framework, schema registry,
  or MCP authorization model.
- No implementation of GCP range provisioning semantics beyond the image/deploy
  contracts required by issue #505.
