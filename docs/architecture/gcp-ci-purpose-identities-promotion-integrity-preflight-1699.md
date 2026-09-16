# GCP CI Purpose Identities And Promotion Integrity Preflight (#1699)

Status: pre-implementation guidance

Date: 2026-09-06

Issue #1699 is the shipping contract. This is a requirement-free run. This
note refines ADR-004-R23 and its #1690 design authority; it does not change a
workflow, cloud identity, image, GitHub Environment, secret, or deployment.

## Decision Boundary

The change stays in the existing GCP CI workflows, foundational WIF/IAM
Terraform, Packer validation scripts/tests, bootstrap and secret documentation,
and repository security checks. It adds no application API, DTO, model,
migration, service/repository layer, exception hierarchy, logging framework,
cloud-provider abstraction, image registry, or promotion database.

Purpose separation is incomplete unless authorization can distinguish the
purpose. Under the repository's verified default GitHub OIDC subject format,
an Environment job emits `repo:ORG/REPO:environment:NAME`; its workflow path and
job are not in `sub`. Consequently the current build and validation jobs share
the same `dev`/`proof` subjects, and deploy and destroy now share `gcp-dev`.
Different service-account emails or Terraform resource names do not isolate
those jobs: either holder of the shared subject could request either account.

Retain the default repository OIDC subject contract established by #1690 and
give each purpose a distinct Environment subject. A repository-wide custom
subject-template migration would affect AWS and every GCP caller and is not
part of #1699. The purpose Environment names are:

| Purpose | GitHub Environment subject context |
| --- | --- |
| Packer build | `gcp-build-dev`, `gcp-build-proof` |
| Candidate validation | `gcp-validate-dev`, `gcp-validate-proof` |
| Prod promotion | `gcp-promote-prod` |
| Platform deploy and its post-deploy verification | existing `gcp-dev` |
| Platform destroy | `gcp-dev-destroy` |

The logical `dev`/`proof` workflow input remains a closed choice and maps to
these literal names. It is not itself an Environment name or a subject. Every
new Environment must carry the applicable protected-branch policy and existing
approval posture before IAM cutover. Environment creation, policy mutation,
secret writes, Terraform apply, and smoke dispatches remain operator actions,
never PR effects.

## Architecture Decisions And Guardrails

### Identity and trust topology

- Keep `packer_build` as the build caller, builder-VM, Cloud Build, and export
  identity. Its self-scoped `serviceAccountUser` and
  `serviceAccountTokenCreator` bindings remain intentional. Remove the
  `GCP_PACKER_SERVICE_ACCOUNT` override/fallback ambiguity: the one Terraform
  build-SA output is the identity used by WIF, Packer, the export worker, and
  the build-targeted IAP firewall. A separately selectable VM identity would
  require a separately designed `actAs` boundary and is not needed here.
- Add explicit validate, promote, deploy, and destroy service accounts in the
  existing `modules/cicd-oidc-identity` module. Deploy and destroy are separate
  even when some Terraform lifecycle permissions overlap: their distinct
  subjects prevent an ordinary deploy job from obtaining destructive identity
  and give Audit Logs an unambiguous principal.
- A single WIF pool/provider may continue to admit the small union of exact
  purpose subjects. The service-account binding is the capability boundary.
  Keep one purpose-to-exact-subject source of truth and derive each SA's
  `principal://.../subject/<sub>` members from its own set. Subject sets must be
  pairwise disjoint. The provider condition must equal their union and pair each
  admitted Environment subject with its allowed full `assertion.ref` values.
  Repository principalSets, wildcard subjects, and a broad cross-purpose SA
  binding are forbidden.
- Keep `allowed_workflow_refs` as the canonical full-ref seam. `dev` and `main`
  are the image paths' protected refs. The existing `gcp-dev` exception is
  admitted only for the existing deploy Environment subject and only if live
  branch protection and the Environment deployment policy confirm it is
  protected. Tags, pull requests, and feature branches receive no provider or
  SA authorization.
- Publish explicit outputs and consume explicit secret names:
  `GCP_PACKER_BUILD_SERVICE_ACCOUNT`,
  `GCP_PACKER_VALIDATE_SERVICE_ACCOUNT`,
  `GCP_PACKER_PROMOTE_SERVICE_ACCOUNT`, `GCP_DEPLOY_SERVICE_ACCOUNT`, and
  `GCP_DESTROY_SERVICE_ACCOUNT`. Keep the existing
  `GCP_WORKLOAD_IDENTITY_PROVIDER` binding. Do not dynamically construct a
  secret name and do not retain `GCP_SERVICE_ACCOUNT` as a compatibility
  fallback; an incomplete cutover must fail before authentication.
- An identity lives in the project whose resources it mutates. Promotion's
  target project owns the promote SA and target mutation role; the dev/source
  project owns the exact source-image read grant to that SA. Cross-project IAM
  is declared by the resource-owning Terraform, never added by workflow shell.
  The foundational root remains separate from platform-core state so platform
  destroy cannot remove the identities needed to rebuild it.

### Capability boundaries

| Identity | Allowed capability | Required exclusions |
| --- | --- | --- |
| Build | Existing Packer VM/image lifecycle, IAP to builders, Cloud Build export, self `actAs`/token minting, and resource-scoped access to the exact export/stack buckets | Platform deploy/destroy, IAM administration, project-wide Storage Admin, validate/promotion subjects |
| Validate | Read/resolve the selected image; create, inspect, reset, and delete the run-scoped no-SA VM; use the validation subnet and IAP ports; set evidence labels on the exact candidate | Service-account attachment/`actAs`, Cloud Build, storage, IAM, platform deploy/destroy, image create/delete/deprecate, prod access |
| Promote | Read/use the exact dev image; create, inspect, label/channel, and deprecate images in the prod target | Source-image mutation, instance lifecycle, IAP, storage, Cloud Build, IAM, platform deploy/destroy |
| Deploy | Current platform-core apply, backend, Connect Gateway, image push, render, rollout, and post-deploy readback capabilities, with build/export permissions removed | Packer build/validate/promote subjects and capabilities |
| Destroy | Backend state read/write plus the platform-core refresh, deletion-protection update, state removal, and destroy operations actually exercised by `gcp-dev-destroy.yml` | Build/validate/promote, secret writes outside Terraform lifecycle, and deploy subject |

Use exact custom roles where predefined roles grant unrelated mutation,
especially validate and promote. Permission lists are derived from the checked-in
`gcloud` commands and Terraform provider operations, then confirmed through a
reviewed plan, Policy Troubleshooter where applicable, and Audit Logs. Do not
add a role on the first 403 without tracing which checked-in operation requires
it. Resource-level bucket bindings stay with `packer-build-infra` and the state
bucket owner; `roles/storage.admin` is not a substitute.

The no-service-account validation VM must remain no-SA/no-scopes. The existing
Packer IAP firewall targets the build SA and therefore does not authorize that
VM. Extend `packer-build-infra` with a validation-only network target and an
IAP-source firewall for only the exercised probe ports; do not attach the
validator SA to the guest to make the current firewall match. Candidate code
must never receive the runner's label authority from the metadata server.

The platform root's deterministic `deploy_service_account_email`, the
resource-scoped GKE-node `actAs` binding in `portal/iam`, and the
Packer-infrastructure SA reference must be rewired to their actual purpose
outputs. Do not rename the old shared local while leaving it connected to both
modules. Both deploy and destroy need explicit resource-scoped backend access;
the deploy workflow must not grant a broad/shared CI identity bucket IAM at
runtime as a hidden compatibility path.

### Validation evidence and channel commit

Strengthen the existing JSON artifact and verifier; do not create a second
manifest or registry. Version the evidence shape and bind at least:

- canonical repository and validator workflow path;
- full protected source ref, event commit SHA, run ID, and run attempt;
- source environment/project, image name, server-assigned numeric GCE image ID,
  family, and image type;
- the two existing health phases, result, and validation timestamp.

The numeric image ID is part of the release identity because a deleted GCE
image name may later be reused. A project/name-only artifact can therefore be
replayed against a different resource. Produce JSON with `jq` and strict
arguments rather than interpolating a shell here-document into JSON.

Upload one success-only immutable artifact, then record its exact artifact ID
along with validation run, attempt, and revision on the candidate. Labeling is
the final validation publication step. A partial/failed validation may leave an
orphan VM or artifact for cleanup, but it must not publish a promotable label
set. Artifact display name alone is not an identity and must not select among
artifacts from reruns.

Promotion uses its job-scoped `actions: read` token against the canonical
repository to fetch the exact artifact record and run metadata. It verifies the
artifact is present, unexpired, immutable, from the referenced run, and has the
expected name; the run is a successful `workflow_dispatch` of exactly
`.github/workflows/packer-gcp-validate.yml` from an allowed full protected ref
and matching commit; and the strictly parsed, versioned evidence matches every
expected candidate field including the current numeric image ID. Missing,
expired, ambiguous, malformed, old-schema, unsuccessful, or mismatched evidence
fails closed. There is no label-only or newest-in-family fallback.

Re-read the source image ID immediately before copying. Create the destination
image without assigning the prod family, then verify READY status and the
provider-reported `sourceImageId` against the validated numeric source ID. Only
after those checks does promotion attach the destination to the family (the
deployment channel) and then deprecate the previous head. Creating directly in
the family changes the channel before verification and is forbidden. A failure
before the family update leaves the previous head unchanged. Promotion labels
carry the safe run/revision/candidate provenance needed for audit, not secrets
or a substitute trust record.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Foundational WIF/IAM | `platform/terraform/gcp/global/cicd-oidc/**`, `platform/terraform/gcp/modules/cicd-oidc-identity/**` | Extend the existing long-lived root/module, exact-subject principals, ref condition, project/environment derivation, and outputs. No second pool module, static keys, or hand-created SAs. |
| Build infrastructure | `platform/terraform/gcp/modules/packer-build-infra/**` | Keep the builder subnet, build-SA-targeted IAP rule, and resource-owned export bucket grant; add the no-SA validator's distinct firewall target here rather than in workflow shell. |
| Platform identity wiring | `platform/terraform/gcp/environments/gcp-dev/main.tf`, `modules/platform-core`, `modules/portal/iam` | Pass the deploy identity through the existing `deploy_service_account_email` seam and resource-scoped node-SA `actAs` grant; keep build and deploy identities distinct. |
| GCP workflows | `packer-gcp.yml`, `packer-gcp-validate.yml`, `packer-gcp-promote.yml`, `_gcp-dev.yml`, `gcp-dev-destroy.yml`, and caller `deploy.yml` | Preserve job-local permissions, pre-auth ref checks, immutable checkout, explicit secret declarations/forwarding, safe environment mapping, `::error::` failures, summaries, and cleanup. |
| Candidate validation | `shifter/packer/gcp/scripts/validate/{linux,dc-probe,gather-evidence}.sh` | Preserve runner-gathered evidence, exact family/profile binding, no-SA/no-public-IP/Shielded posture, IAP, reboot proof, bounded retries, and failure-safe cleanup. Do not move trust into guest code. |
| Evidence verification | `verify-promotion-evidence.sh` and `TestGcpPromotionEvidenceBinding` | Evolve the one JSON/verifier contract with strict typed fields and negative cases. Do not duplicate verification inline in the workflow or add another schema package. |
| Promotion transaction | `packer-gcp-promote.yml` and `TestGcpPromoteEvidenceDriven` | Preserve exact-source selection and previous-head handling; make family assignment the final verified channel commit rather than introducing a new pointer store. |
| Secret/config validation | `scripts/bootstrap/preflight.py`, `scripts/bootstrap/gcp_control_plane.py`, `docs/dev/deploy-secrets.md`, and reusable-workflow secret declarations | Extend explicit required-value checks and output-to-secret documentation. Keep logical environment choices separate from purpose Environment names; no dynamic secret lookup or silent fallback. |
| WIF enforcement | `scripts/check_tf_gcp_wif_trust/**`, `.pre-commit-config.yaml`, `_quality.yml`, `docs/adr/index.yaml` | Extend the existing semantic guard to reconcile the provider union, pairwise-disjoint per-SA exact subjects, and caller inventory. Keep comment stripping and positive/negative tests. |
| Permission enforcement | Existing `scripts/check_tf_*` effective-permission test pattern and blocking Terraform Checkov config | Add an effective CI-identity permission oracle beside the WIF guard (or a narrowly named checker if parsing cannot remain cohesive). Do not fold CI principals into the application-workload-specific `check_tf_gcp_iam_resource_scope` policy or rely on resource labels/string presence. |
| Workflow security model | ADR-003-R5, ADR-004-R23, `scripts/adr_guard/tests/test_deploy_workflow.py`, and the workflow action-pinning/exposure model | Keep mutation off PRs, Environment binding, full-SHA action pins, and checkout credential non-persistence. Semantic inventory must cover all five callers and the `_gcp-dev` smoke auth job. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **Dispatch and input shape.** Image type and logical environment stay closed
   choices. Candidate, family/profile, project, numeric image ID, run/artifact
   IDs, SHA, and ref receive strict syntax/type checks before interpolation into
   commands, environment files, labels, paths, or JSON. A free-form input never
   selects executable code, an Environment, a secret name, or an SA.
2. **GitHub authorization and Environment policy.** Every credentialed job binds
   its literal purpose Environment, requests only its job permissions, and runs
   the event SHA with `persist-credentials: false`. Live Environment branch
   policies and approvals are read back before cutover. Approval, ref policy,
   OIDC subject, and workflow path are separate facts; none is described as the
   other.
3. **WIF provider and SA impersonation.** Repository, full ref, and exact subject
   all pass at the provider; a pairwise-disjoint exact-subject SA binding then
   selects capability. Tokens are short lived. No key JSON, repository
   principalSet, wildcard, caller-supplied provider/SA, or shared fallback exists.
4. **GCP IAM/resource policy.** Each effective permission set matches its
   checked-in calls. Cross-project source reads, bucket access, node-SA `actAs`,
   IAP ingress, and target image mutation are granted by their resource owners.
   Validate/promote receive neither broad deploy roles nor each other's writes.
5. **Configuration shapes.** Terraform variables/validation, module outputs,
   `allowed_workflow_refs`, explicit reusable-workflow secrets, bootstrap
   required-secret checks, and current logical environment choices remain the
   canonical schemas. No YAML identity-policy DSL or second environment mapper
   is introduced.
6. **Guest/network boundary.** The candidate VM has no external IP, service
   account, or OAuth scopes; Shielded VM assertions, blocked project SSH keys,
   purpose-targeted IAP firewall, runner-held ephemeral key, and runner-side
   probes all remain mandatory. Guest output never constitutes the trust record.
7. **Secret and OS/process exposure.** Auth action credentials and GitHub token
   remain in action-managed environment/temporary files, never argv or
   artifacts. Private SSH material and downloads live under `RUNNER_TEMP`, use
   restrictive permissions where created, and are removed by cleanup. Do not
   enable shell tracing, persist checkout credentials, dump environments, or
   upload a workspace/credential file.
8. **Evidence persistence.** GCE labels are bounded locators/indices; the exact
   immutable Actions artifact plus run metadata is the evidence record; the GCE
   numeric ID identifies the candidate; the image family is only the deployment
   channel. No database, Redis, object bucket, parameter namespace, or mutable
   registry is added.
9. **Error envelope and observability.** Continue `set -euo pipefail`, non-zero
   exits, `::error::`/`::warning::`, and safe step summaries. Diagnostics may
   identify purpose, phase, environment, run/attempt, commit, candidate name/ID,
   and expected field, but not tokens, credential paths/content, complete claim
   payloads, policy documents, secret values, or raw API bodies. Cleanup failure
   stays visible without replacing the primary result. GitHub run history and
   GCP Audit Logs provide authoritative correlation by distinct principal.
10. **Repository enforcement.** Actionlint, action-SHA and runner-exposure ADR
    checks, Terraform fmt/validate/TFLint/blocking Checkov, WIF/permission
    semantic checks, Packer behavioral tests, bootstrap tests, quality ownership,
    and full ADR guard must see the change. Negative cases cover subject overlap,
    wrong purpose/ref/Environment, broad roles, missing/expired/wrong artifact,
    rerun ambiguity, name-reuse/image-ID mismatch, source race, and premature
    family mutation.

## Extensibility Seam

The seam is an explicit purpose with (a) its literal Environment subject set,
(b) allowed full refs, (c) Terraform-owned SA/permission set, and (d) explicit
output/secret. The provider condition is the checked union, while each SA sees
only its purpose subset. A future image stage or GCP environment adds one
purpose/environment entry and its explicit identity; it does not edit every
workflow's trust expression or inherit build/deploy permissions.

The evidence seam is a versioned extension of the existing JSON artifact keyed
by project/name/numeric image ID and run/artifact ID. A future validation phase
extends that schema and verifier together. It does not create a new registry or
change the image family from channel to evidence store.

## Gotchas And Anti-Patterns

- Do not call two SAs isolated when they accept the same default Environment
  subject; secret names are configuration, not an authorization boundary.
- Do not change the repository-wide OIDC customization to avoid creating
  purpose Environments; that silently changes AWS and every GCP subject.
- Do not bind build and validate to `environment:dev`/`proof`, or deploy and
  destroy to `environment:gcp-dev`, after the split.
- Do not retain `GCP_SERVICE_ACCOUNT` or `GCP_PACKER_SERVICE_ACCOUNT` as a
  fallback that restores the old shared privilege on missing configuration.
- Do not attach the validator SA to the candidate VM, give it scopes, or reuse
  the build-SA-targeted firewall; the guest executes candidate-controlled code.
- Do not grant validate `compute.admin`, promote source-image mutation, or either
  identity project IAM/Storage/Cloud Build/platform roles for convenience.
- Do not let workflow shell create cross-project IAM or backend bucket grants.
- Do not trust an image name, family, label, artifact name, workflow display
  name, branch short name, or successful conclusion alone. Verify their distinct
  canonical fields and the candidate numeric ID.
- Do not use `gh run download --name` as the artifact identity after reruns;
  resolve and download the exact artifact ID associated with the referenced run.
- Do not construct evidence JSON with unescaped here-document interpolation,
  parse it with grep, tolerate missing fields, or accept an unknown schema.
- Do not create the prod copy with `--family`; that can advance the channel
  before provenance and readiness checks finish.
- Do not resolve newest-in-family on the source side, mutate/deprecate the old
  prod head before the replacement is verified, or make cleanup hide the
  primary failure.
- Do not put CI identity permissions into the application workload IAM checker,
  duplicate subject/environment maps in tests and production, or use comments
  and substring tests as the security gate.
- Do not weaken Checkov, TFLint, action pinning, ADR guard, protected Environment
  rules, or evidence checks to make staged cutover pass.

## Non-Goals And Implementation Boundaries

- No application auth/Identity Platform redesign, runtime workload IAM change,
  range guest identity change, guest image content change, or Packer provisioner
  redesign.
- No new promotion database, image registry, storage bucket, SSM-like pointer,
  general cloud-identity framework, provider-neutral image schema, or policy DSL.
- No repository-wide GitHub OIDC subject customization and no change to AWS
  OIDC trust.
- No broad least-privilege redesign of platform-core Terraform. Deploy/destroy
  permissions are separated and stripped of image-build capability; deeper
  platform role decomposition requires its own exercised-operation inventory.
- No split of `_gcp-dev`'s advisory post-deploy smoke into another identity in
  this issue. It remains deployment verification under the deploy Environment
  and identity and must be included in caller/permission tests.
- No live Terraform apply, GitHub secret/variable/Environment mutation, image
  validation/promotion, deployment, destroy, merge, or cutover in the PR.

## Validation Expectations

Implementation must run the repository-required ADR guard, actionlint, GCP
Terraform TFLint, affected-root Terraform fmt/validate with the canonical
inventory, blocking Checkov, the WIF/permission checker suites, Packer tests,
and bootstrap/deploy workflow tests. Reviewed plans must show the old shared WIF
members and mixed roles removed rather than retained as compatibility paths.
Operator readback must cover repository OIDC customization, every purpose
Environment's branch/reviewer policy and secret presence, provider condition,
each SA's exact WIF members and effective IAM policy, resource-scoped cross-
project/bucket/firewall grants, and GCP Audit Logs from one protected positive
smoke plus denied wrong-purpose/ref probes. Revalidation is the recovery for
expired or invalid evidence; label-only promotion is never recovery.
