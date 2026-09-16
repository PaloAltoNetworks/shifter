# REV1 Build And Deployment Provenance Preflight (#1519)

> **Historical boundary (issue #2062, 2026-08-19):** TechVault is a
> scenario pack. APTL is the former name of LilRAE. The bespoke Shifter
> implementation described here was retired by the RAES hard cut. Exact
> historical commands, paths, symbols, image keys, and workflow names below
> remain factual evidence; they are not current product or integration
> boundaries.

Status: pre-implementation guidance

Date: 2026-07-12

Issue: GitHub #1519, "REV1 Security: establish verifiable build and deployment provenance"

This requirement-free issue is governed by its GitHub acceptance criteria. This
note records trust-boundary decisions and is not an implementation plan.

## Boundary And Decision

Treat build provenance as a delivery-plane security control, not an application
feature. It belongs in the existing GitHub Actions build/deploy workflows,
Dockerfiles, Packer provisioners, and image-reference renderers. It must not
add a Django API, database record, Terraform resource, custom signer service,
or a second deployment framework.

- Every non-local `uses:` action in a cloud-credentialed workflow is an
  executable dependency and must be pinned to a reviewed, full commit SHA.
  This includes `actions/*`, not only community actions. Local reusable
  workflow references remain local paths.
- Every committed Docker `FROM` is a build input: pin every stage, including
  builder stages and scenario containers, to a digest. A tag may appear only in
  a human-readable comment/refresh record, never as the resolved build input.
  A builder can execute code and influence the released image, so calling it
  "build only" is not an exemption.
- Use the existing Dependabot Docker update convention as the base-image
  refresh mechanism. Extend it to each Dockerfile directory in scope and keep
  its weekly reviewed PR flow; the current portal-only comment must match the
  actual pins after the change. A digest refresh changes the digest and the
  adjacent version comment together, then runs the relevant image build.
- The existing `docker/build-push-action` build digest is the one identity
  carried forward. Build with explicit SBOM and maximum provenance metadata,
  then create a GitHub OIDC-signed artifact attestation for that exact
  repository name plus digest. BuildKit metadata alone is useful but is not the
  deployment authorization decision.
- Deployment verifies the same fully qualified `image@sha256:...` with the
  GitHub attestation verifier and the fixed `Brad-Edwards/shifter` repository
  identity before it mutates ECS, SSM-backed portal rollout, or Kubernetes.
  A valid signature for another repository, a tag resolving to a digest, or a
  digest merely matching the expected shape is not sufficient.

The release OCI image set is portal, provisioner, guacd, and guacamole-client
in both ECR and Artifact Registry. AWS already has an engine and portal digest
flow; retain it and place attestation verification immediately before the
existing rollout commands. GCP must extend its existing runtime-env/Helm
rendering seam from immutable-looking short-SHA tags to resolved digest
references; do not add a parallel manifest renderer.

Packer AMI/GCE images are not OCI images and must not be represented as such.
Their credentialed workflows and executed provisioners are in scope for action
pinning and verified downloads. If "release images" is intended to include VM
images, attest the immutable Packer manifest/SBOM keyed by the AMI or GCE image
identifier and verify that manifest at promotion/consumption; do not claim the
OCI attestation proves a VM-image release. The implementation must make that
scope decision explicit in its operator documentation.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Workflow routing, runner exposure, and deploy ordering | `.github/workflows/deploy.yml`; ADR-003-R5 | Preserve trusted-event routing, GitHub Environment binding, and reusable-workflow input propagation. Do not add a provenance-only deploy workflow. |
| AWS OCI build and rollout | `.github/workflows/_shifter-engine.yml`, `.github/workflows/_shifter-platform.yml` | Preserve build outputs, ECR login, ECS task-definition rewrite, Parameter Store digest, ASG digest verification, and fail-loud rollout checks. Add verification around these existing hand-offs. |
| GCP OCI build and rollout | `.github/workflows/_gcp-dev.yml`, `scripts/gcp/render_runtime_env.py`, `platform/charts/shifter/**`, `platform/k8s/gcp/**` | Resolve and render image digests through the existing generated runtime environment and chart values. Do not patch individual workload manifests or create a second image-values schema. |
| Existing image identity contract | `platform/terraform/modules/engine-provisioner/task_definition.tf`, `scripts/portal_deploy/portal_deploy.py` | Keep the current ECR digest contract; a tag remains diagnostic metadata only. |
| Python lock-and-hash pattern | `shifter/shifter_platform/uv.lock`, `shifter/shifter_platform/requirements-gcp.lock`, and its Dockerfile `uv export --frozen` / `--require-hashes` install | The platform image already meets the intended pattern. Bring provisioner and scenario runtime installs to an equivalent reviewed lock/hash flow; do not keep a separately resolved `requirements-gcp.txt` with `>=` constraints. |
| Packer build surface | `shifter/packer/**`, `.github/workflows/packer*.yml`, `shifter/packer/tests/test_packer.py` | Keep provider-specific AMI/GCE mechanics separate while hardening the downloaded executable inputs they run. |
| Workflow policy tests | `scripts/adr_guard/adr_guard.py` workflow-as-data helpers and `scripts/adr_guard/tests/test_deploy_workflow.py` | Extend the existing policy suite to identify credentialed workflows and reject mutable action refs. Do not create another substring-only workflow scanner. |
| Guardrails and refresh process | `.github/dependabot.yml`, `.github/workflows/_quality.yml`, `.pre-commit-config.yaml`, `scripts/adr_guard/adr_guard.py`, `actionlint` | Keep Dependabot as the refresh cadence and existing quality/ADR gates as enforcement. |

## Required Cross-Cutting Layers

| Layer | Required treatment |
| --- | --- |
| GitHub auth and permissions | Keep AWS OIDC and GCP Workload Identity Federation. Attestation build jobs receive only the narrowly required OIDC, repository-read, attestation-write, and registry permissions; no long-lived signing key, PAT, or cloud credential is introduced. Deployment verification receives read-only attestation access. |
| Workflow config shape | Reuse `workflow_call` inputs, job outputs, and the current `{image_tag, image_digest}` contract. The extensibility seam is a provider-neutral `image_name + immutable_digest` verification input, with provider-specific registry authentication remaining in its current workflow. Do not pass a free-form image string or a bypass boolean. |
| Download integrity | The provisioner Dockerfile must verify Terraform and Pulumi before extraction. The same requirement applies to executable payloads downloaded by credentialed workflow steps and Packer provisioners, including the current kubeconform download, `curl | sh` bootstrap paths, SSM-agent package, and direct Windows installers. Prefer an official signed checksum/manifest verified before execution; package-manager repository signatures are a distinct package-manager control. Never replace a verifier with a version-pinned URL alone. |
| Runtime dependency integrity | Platform's frozen hashed install remains authoritative. Provisioner `requirements.txt`/`requirements-gcp.txt` and direct scenario `pip install` calls are currently insufficient even where versions are exact: a reviewed lock or hash export must drive install with hash enforcement. CI-only helper downloads must be reviewed separately and must not be mistaken for runtime lock coverage. |
| Base-image integrity and refresh | Every `FROM` resolves only to `@sha256`. The current comments claiming digest pins while the portal stages use tags are documentation/config drift and must be corrected. Digest refresh is a reviewed Dependabot-driven change, not a floating-tag security rebuild. |
| Registry and deployment identity | Build output digest must be associated with the exact repository, signed provenance, and SBOM. AWS keeps its ECR digest plumbing; GCP turns the build output into the existing generated runtime image value. Before rollout, verifier failure, missing attestation, repository/subject mismatch, or digest mismatch is a hard `::error::` and non-zero exit. |
| OS/process and secret handling | Use temp files/standard input where an attestation or checksum tool requires a file; delete them after use. Never place cloud credentials, rendered tfvars, GitHub tokens, attestation bundles, or full task definitions in argv, shell tracing, step summaries, or artifacts. Image names and digests are safe diagnostics. |
| Error and observability surface | Use existing GitHub Actions annotations and fail-loud job semantics. Log provider, image logical name, repository, expected digest, verifier class, and non-secret failure category. Do not print raw attestation JSON, certificate material, HTTP authorization data, or secret-bearing task-definition/config payloads. |

## Scope And Guardrails

The action-pin policy covers the direct cloud-auth workflows and their reusable
orchestration surface: `deploy.yml`, `_core.yml`, `_range.yml`,
`_shifter-engine.yml`, `_shifter-platform.yml`, `_gcp-dev.yml`,
`gcp-dev-destroy.yml`, `packer.yml`, `packer-promote.yml`, `packer-gcp.yml`,
`packer-gcp-promote.yml`, `polaris-scenario-bake.yml`, and
`techvault-scenario-bake.yml`. The current mutable refs in the AWS reusable
workflows, Packer promotion/build workflows, Polaris/TechVault bakes, and
top-level deploy orchestration are all in scope even when an equivalent GCP
workflow is already SHA pinned.

Image/input scope includes the Dockerfiles under `shifter/engine/**`,
`shifter/shifter_platform/**`, and `scenario-dev/polaris/containers/**`; the
provisioner CLI downloads; `_gcp-dev.yml`'s kubeconform download; and the
download/install paths executed by the Packer and scenario-bake workflows.
This is intentionally broader than the four direct control-plane OCI builds:
the scenario and Packer sources execute with cloud credentials or produce
deployable range material.

The policy test must fail closed when it cannot classify a `uses:` reference,
when a credentialed workflow is added without coverage, or when a reference is
not a full SHA. It should parse workflow data through the existing ADR guard
model, rather than infer security from comments, filenames, branch names, or a
hand-maintained list of action versions. Retain readable release-version
comments next to SHA pins so Dependabot updates remain reviewable.

## Gotchas And Anti-Patterns

- Do not treat a short SHA image tag as immutable identity. It is a naming
  convention, while registry tags remain mutable; render and deploy the
  registry digest.
- Do not use a tag plus digest to satisfy both a scanner and reproducibility.
  Use a digest-only `FROM` with an adjacent version comment and adjust the
  scanner/configuration honestly if it rejects a required security control.
- Do not silently trust Buildx's default minimal provenance, an SBOM file
  generated but not attached/signed, or an attestation generated but never
  verified at deploy time.
- Do not verify only signature cryptography. Bind verification to the expected
  Shifter repository, workflow identity, fully qualified image repository, and
  exact digest.
- Do not create a generic image-trust database, admission controller, custom
  key-management service, Terraform data source, or a second image-reference
  DTO. Existing workflow outputs and provider renderers are the contract.
- Do not let an explicit first-deploy exception, `continue-on-error`, missing
  CLI, registry lookup failure, or verifier network error become a warning.
  This issue has no trust-bypass mode.
- Do not pass credentials as Docker build arguments: maximum provenance can
  expose build arguments. Use the existing secret/environment handling and
  BuildKit secret mounts only where a build genuinely needs a secret.
- Do not imply that package-manager signing, VM-image provenance, dependency
  vulnerability scanning, SBOM generation, and image-signature verification
  are interchangeable controls. Each proves a different claim.

## Non-Goals

- No change to cloud IAM trust policies, GitHub Environment routing, runner
  topology, Terraform state, ECS/GKE topology, application APIs, persistence,
  or runtime business behavior.
- No redesign of Packer source-AMI/GCE-family selection, OS package repository
  policy, or the intentionally vulnerable CTF scenario content. Unverified
  executable downloads in the credentialed build path must still be fixed;
  broad hermetic OS package rebuilds are not required by this issue.
- No replacement of Dependabot, actionlint, ADR guard, existing dependency
  managers, or the current deploy preflight with a new supply chain platform.
- No claim that provenance attestation remediates CVEs, authorizes arbitrary
  third-party images, or replaces image vulnerability scanning and existing
  deployment health verification.
