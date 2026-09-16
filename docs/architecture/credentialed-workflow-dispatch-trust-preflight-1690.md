# Credentialed Workflow Dispatch Trust Preflight (#1690)

Status: pre-implementation guidance

Date: 2026-07-17

Issue #1690 is the shipping contract. This is a requirement-free run. This
note does not change a workflow, cloud role, Workload Identity provider,
service account, GitHub Environment, image, or deployment.

## Decision Boundary

Credentialed `workflow_dispatch` provenance must be enforced before dispatched
workflow code can obtain a cloud identity. A ref check inside that workflow,
an Environment approval, and a checkout with no free-form `inputs.ref` are
useful controls, but none independently proves reviewed-code provenance.

Extend ADR-004-R22's exact-subject pattern to the remaining credentialed
dispatch paths under new ADR-004-R23. ADR-003-R5 continues to own credentialed
job routing and GitHub Environment binding. The current ADR-029 is the SPA
cutover decision and is not an authority for this change despite the historical
issue reference; do not attach workflow trust policy to it.

This issue stays in existing workflow, IAM/WIF Terraform, Packer validation,
bootstrap/runbook, and repository-guardrail surfaces. It adds no application
API, DTO, model, migration, repository, service, exception hierarchy, logging
framework, image registry, or general cloud-identity abstraction.

## Architecture Decisions And Guardrails

- Verify the repository's live GitHub OIDC customization before choosing any
  subject string. The established check is
  `gh api repos/Brad-Edwards/shifter/actions/oidc/customization/sub`; the
  expected contract is `use_default: true` and `use_immutable_subject: false`.
  A different live result blocks rollout until the Terraform subjects are
  designed for that actual format. Do not guess or silently change the
  repository customization to fit the code.
- AWS trust for `aws_iam_role.github_actions` must replace
  `repo:${var.github_org}/${var.github_repo}:*` with an explicit union of the
  exact subjects its inventoried callers emit. Jobs without `environment:` use
  exact protected branch subjects (`ref:refs/heads/dev` and
  `ref:refs/heads/main`). Environment-bound jobs use exact
  `environment:<name>` subjects for the existing `aws-<environment>`
  environments. Each role instance should admit only the environment subject
  that matches `var.environment`, plus only the exact branch subjects genuinely
  needed by its non-Environment callers. Pull-request, tag, and feature-branch
  subjects receive no role.
- An Environment subject no longer contains the branch. Therefore every
  GitHub Environment whose subject is trusted by AWS or GCP must have a
  deployment-branch policy allowing only the protected branches. Required
  reviewers are deployment authorization; deployment-branch policy is the
  reviewed-code provenance control. Both are useful, but they are not the same
  concept.
- GCP federation must require the exact repository, an exact protected
  `assertion.ref`, and an exact allowed `assertion.sub`. Service-account WIF
  bindings must use exact `principal://.../subject/<sub>` members, not the
  repository-wide `principalSet/.../attribute.repository/...` binding. The
  current repository-only provider condition and CKV_GCP_125 waiver must not
  survive the cutover.
- A single GCP provider may carry the small explicit union of subjects needed
  by its callers, but authorization remains service-account-specific. Keep the
  existing Packer build identity for build capability; add separate validation
  and promotion identities with only their exercised permissions. Validation
  may inspect candidates, create/reset/delete the disposable no-service-account
  VM, use IAP, and write validation evidence. Promotion may read the exact dev
  image and create/verify/deprecate the destination image. Neither identity
  receives platform deploy, IAM administration, Cloud Build, arbitrary storage,
  or the other workflow's mutation capability merely for convenience.
- The AWS base-image `build` job and `github_actions_image` role remain governed
  by ADR-004-R22 and are out of scope. The `packer.yml` `bake-scenario` job is
  not that base-image job: it still resolves the broad deploy role and executes
  a mutable `inputs.ref` checkout. It must not be described as already having a
  separate role boundary. Give the scenario path an explicit least-privilege
  principal, or keep it blocked until that principal's Packer, S3, SSM, EC2,
  KMS, and exact `iam:PassRole` contract is defined. Do not widen the R22 base
  role or preserve the general deploy role to make the two jobs look uniform.
- Once external trust accepts only a protected dispatch ref, credentialed code
  is checked out by the event commit (`github.sha`) explicitly. Do not resolve
  a mutable branch name again after authorization. A caller-selected ref may be
  retained only as non-executable source data with its own immutable commit or
  digest; it must not select workflow logic, Packer templates, validators,
  shell/PowerShell scripts, or promotion code.
- `validated=passed` is not sufficient evidence by itself. The existing build
  identity has broad Compute Engine image capability, so a new validator service
  account does not make that label exclusive. Promotion must bind the existing
  `validated-run`, source revision, and validation-evidence artifact to the
  exact candidate and verify that the referenced run is a successful
  `packer-gcp-validate.yml` run from an allowed protected ref/commit. Missing,
  expired, malformed, candidate-mismatched, or non-success evidence fails
  closed and requires revalidation; there is no label-only fallback.
- Keep workflow permissions job-local and minimal: `contents: read` plus
  `id-token: write` only where federation occurs, and `actions: read` only if
  promotion reads the validation run/artifact. Continue SHA-pinning every
  action under ADR-037-R1. Checkout credentials are not persisted on
  self-hosted runners.
- GitHub Environment policies and cloud trust changes are live external state,
  not effects of merging Terraform text. The implementation PR must document a
  fail-closed cutover and readback for every affected environment, role,
  provider, service account, and secret. Do not leave a repository wildcard as
  a compatibility path; stage the cutover so an unconfigured caller fails
  rather than silently retaining broad trust.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| AWS deploy trust and outputs | `platform/terraform/global/iam/github-oidc.tf`, `github_actions_role_arn`, `var.environment`, `var.github_org`, `var.github_repo` | Tighten the existing environment-keyed role in place. Preserve `jsonencode`, tags, outputs, bootstrap ownership, category-policy size/attachment limits, and the R22 image role. Do not create another global-IAM root or policy generator. |
| AWS role selection | `scripts/bootstrap/preflight.py`, `scripts/bootstrap/aws_bootstrap.py`, `docs/dev/deploy-secrets.md`, and the explicit role-selection cases in reusable workflows/`packer.yml` | Preserve the `AWS_ROLE_ARN[_DEV|_PROOF]` conventions, missing-value failures, and explicit environment mapping. New workflow identities use the same output/secret wiring convention rather than dynamic secret-name evaluation. |
| AWS credentialed callers | `deploy.yml`, `_core.yml`, `_range.yml`, `_shifter-engine.yml`, `_shifter-platform.yml`, `packer.yml`, and `packer-promote.yml` | Inventory every job that assumes the general role and classify its real branch or Environment subject before changing trust. Do not test only the file named in the issue. |
| GCP federation ownership | `platform/terraform/gcp/modules/cicd-github-oidc`, its `gcp-dev` root wiring, and module outputs | Extend the current pool/provider/service-account module. Keep WIF, self-service-account bindings where required, project/environment derivation, and output-based GitHub configuration. Do not hand-create untracked SAs or introduce keys. |
| GCP credentialed callers | `_gcp-dev.yml`, `gcp-dev-destroy.yml`, `packer-gcp.yml`, `packer-gcp-validate.yml`, and `packer-gcp-promote.yml` | Treat these as one caller inventory because they currently share provider/secret names. A provider-condition change must not accidentally strand deploy, destroy, or build, and no caller may retain repository-wide trust. |
| Candidate validation | `packer-gcp-validate.yml`, `shifter/packer/gcp/scripts/validate/*`, and `TestGcpValidationWorkflow` | Preserve exact candidate/family binding, runner-gathered evidence, no guest SA/scopes, no external IP, Shielded VM assertions, reboot proof, fail-loud checks, evidence upload, and `always()` cleanup. Run this code only from the trusted event SHA. |
| Promotion | `packer-gcp-promote.yml` and `TestGcpPromoteEvidenceDriven` | Preserve exact-candidate copy, family derivation from the candidate, READY verification before old-head deprecation, and previous-head preservation on failure. Strengthen the existing evidence contract; do not add another registry or resolve newest-in-family. |
| Workflow routing and Environment binding | ADR-003-R5, `deploy.yml`'s `github_environment` mapping, and `scripts/adr_guard/tests/test_deploy_workflow.py` | Reuse existing Environment names and binding tests. Add all newly credentialed/mutating jobs to the semantic inventory instead of relying on comments or substring checks. |
| AWS trust guard | `scripts/check_tf_iam_role_naming/` | Extend the existing R22 exact-subject parser/tests to the general deploy role. The check must strip comments, reject wildcard subjects, and assert the environment-derived and protected-branch allowlist without keying only on resource labels. |
| GCP trust guard | Checkov via `platform/terraform/.checkov.yaml` plus the repository's focused `scripts/check_tf_*` checker pattern | Remove the CKV_GCP_125 waiver and add a focused semantic WIF guard with positive/negative tests for provider condition and exact SA members. Do not put GCP WIF semantics into the AWS role-naming checker or rely only on brittle Packer string tests. Wire local and CI parity before shipping. |
| Logs and audit | Existing `::error::`/step-summary conventions, AWS run-scoped role sessions/CloudTrail, GitHub run metadata, and GCP Audit Logs | Report safe subject class, environment, workflow/run, commit, candidate, and phase. Do not dump tokens, credential files, complete claim payloads, environments, policies, or cloud API response bodies. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **Dispatch and input shape.** Environment/image inputs remain closed choices;
   slugs and candidate names keep their existing strict validators. A free-form
   ref cannot select executable credentialed code. Full refs are compared as
   `refs/heads/...`, never `ref_name`, so a tag named `dev` cannot pass.
2. **GitHub authorization.** Workflow permissions remain least privilege.
   Environment-bound jobs use exact known Environment names whose deployment
   branch policies exclude feature branches and tags. Branch-bound jobs are
   admitted only by exact protected-branch cloud subjects. Environment approval
   is not presented as code provenance.
3. **AWS OIDC/STS.** The role trust keeps exact `aud = sts.amazonaws.com` and an
   explicit exact-subject allowlist; `StringLike repo:...:*` is forbidden. Role
   session names remain run-correlatable. No access key, session token, PAT, or
   caller-controlled role ARN is introduced.
4. **GCP WIF/IAM.** The provider condition evaluates repository, ref, and sub;
   the SA binding names an exact subject principal. Dedicated build, validate,
   promote, deploy, and destructive capabilities are not collapsed into the
   existing build SA. Cross-project promotion grants are owned explicitly by
   the affected project Terraform, not granted at runtime by the workflow. The
   protected `gcp-dev` deployment branch is admitted only when paired with the
   exact `gcp-dev` Environment subject; it does not inherit shared build,
   validation, or promotion subjects.
5. **Configuration validation.** Terraform's existing environment validation,
   GitHub org/repo variables, workflow choice inputs, explicit environment-to-
   secret cases, image/profile validation, and `scripts/bootstrap/preflight.py`
   remain the canonical shapes. Do not add a YAML identity-policy schema or a
   second environment mapper.
6. **Checkout and OS/process exposure.** Trusted logic is the immutable event
   SHA. `persist-credentials: false` prevents checkout tokens lingering in Git
   config on self-hosted runners. OIDC/AWS/GCP credentials remain action-managed
   environment or temporary credential-file state, never argv. Temporary SSH
   keys/evidence use run-temporary storage and are removed; shell tracing and
   environment dumps stay off.
7. **Secret handling.** Provider resource names, SA emails, role ARNs, project
   IDs, and account-bearing identifiers follow current GitHub secret/redaction
   conventions even where the cloud treats them as identifiers. No token,
   credential JSON, tfvars payload, private key, or raw OIDC claim is placed in
   inputs, summaries, artifacts, labels, command arguments, or committed docs.
8. **Evidence and persistence.** GCE labels are bounded indices, not the full
   trust record. The workflow run plus existing JSON artifact is the validation
   evidence; the exact GCE image is the release unit and the family remains the
   deployment channel. No database, Redis entry, new parameter namespace, or
   mutable artifact registry is introduced.
9. **Error envelope and observability.** Auth, subject, evidence, and promotion
   failures use `::error::` and non-zero exit while naming only the safe field,
   environment, run, commit, candidate, and phase. Cleanup failure is separately
   visible and does not overwrite the primary result. Previous runtime pointers
   or prod family heads remain unchanged on failure.
10. **Repository enforcement.** `actionlint`, Terraform fmt/validate/TFLint,
    Checkov, the AWS IAM checker, the new focused GCP WIF guard, Packer workflow
    tests, bootstrap tests, SHA-pinning guard, deployment-exposure tests, and
    ADR guard must all see the change. Negative tests prove feature refs, tags,
    PR subjects, wildcard trust, repository principalSets, wrong environments,
    mutable code refs, and mismatched validation evidence fail closed.

## Caller And Whole-Repo Inventory

- AWS general deploy role: the plan/apply/build/deploy/verify/smoke jobs in
  `_core.yml`, `_range.yml`, `_shifter-engine.yml`, and
  `_shifter-platform.yml`; dispatch routing in `deploy.yml`; scenario bake in
  `packer.yml`; and both jobs/role switches in `packer-promote.yml`.
- AWS dedicated base-image role: `packer.yml::build` and ADR-004-R22. Preserve
  it unchanged except for caller-inventory tests needed to prove R23 does not
  route base builds back through the general role.
- GCP shared WIF callers: `_gcp-dev.yml::deploy`,
  `gcp-dev-destroy.yml::destroy`, `packer-gcp.yml::build`,
  `packer-gcp-validate.yml::validate`, and
  `packer-gcp-promote.yml::promote`. `gcp-dev-destroy.yml` currently has no
  Environment binding; it must not be forgotten when repository-wide provider
  trust is removed.
- IaC/config: `platform/terraform/global/iam/**`,
  `platform/terraform/gcp/modules/cicd-github-oidc/**`, the `gcp-dev`
  environment root/outputs, Terraform validation inventory/lockfile if the
  root/module shape changes, and canonical Checkov configuration/exceptions.
- Operator/configuration: `scripts/bootstrap/**`, `scripts/ami.sh`, `mcp/ops`
  AMI dispatch if its ref contract changes, `docs/dev/deploy-secrets.md`, AWS
  AMI seeding/runbooks, and GCP guest-image/operator docs.
- Enforcement/tests: `scripts/check_tf_iam_role_naming/**`, the focused GCP WIF
  guard and its tests, `.pre-commit-config.yaml`, `_quality.yml`,
  `scripts/adr_guard/tests/test_deploy_workflow.py`, and
  `shifter/packer/tests/test_packer{,_gcp}.py`.
- Host/runtime: GitHub-hosted and self-hosted runner workspaces, temporary
  credential files, Git config, process environments/argv, GitHub Environments,
  AWS STS/CloudTrail, GCP WIF/IAM/Audit Logs, GCE image labels, and Actions
  artifact retention.

## Extensibility Seam

The seam is one validated set of full protected refs, parameterized at each
existing Terraform trust owner and consumed to derive provider-native exact
subjects. A future protected branch or environment is added once to that trust
configuration and to its GitHub Environment deployment policy; it does not
require copying trust statements through every workflow.

Capabilities remain explicit named identities (deploy, base-image build,
scenario-image bake, GCP build, GCP validate, GCP promote), not entries in a new
generic policy DSL. A future image stage adds a purpose-specific identity and
evidence transition; it does not inherit the builder or deploy identity merely
because it uses the same cloud or Packer.

## Gotchas And Anti-Patterns

- Do not treat an in-workflow `github.ref`, `inputs.ref`, or `dev|main` check as
  the trust boundary; a feature-ref workflow can remove it before execution.
- Do not assume `github.ref`, `github.sha`, checkout `ref`, OIDC `sub`,
  `assertion.ref`, and `job_workflow_ref` are interchangeable.
- Do not put branch subjects on Environment jobs. Under the default format,
  their `sub` is `repo:ORG/REPO:environment:NAME`.
- Do not trust an Environment subject without a deployment-branch policy; the
  subject itself hides whether the dispatch came from a branch or tag.
- Do not replace the GCP provider condition but leave the repository principalSet
  on the service account. Both layers must be exact.
- Do not share the build SA with validate/promote and call secret-name changes
  least privilege. SA emails are discoverable, and the WIF member is the actual
  impersonation boundary.
- Do not claim the validation label is exclusive while another trusted identity
  can set image labels. Bind promotion to the protected validation run/evidence.
- Do not re-resolve `refs/heads/dev` after dispatch when `github.sha` already
  names the authorized commit; that introduces a branch-movement race.
- Do not omit `packer-promote.yml`, `packer-gcp.yml`, or
  `gcp-dev-destroy.yml` from the caller inventory simply because the issue's
  examples emphasize validate/promote and scenario bake.
- Do not put GCP trust semantics into `check_tf_iam_role_naming`, duplicate
  environment/subject maps in tests and production, or rely on string-presence
  tests as the security guard.
- Do not retain the CKV_GCP_125 waiver, add an expiring wildcard exception, use
  a static cloud key, print auth action outputs, enable shell tracing, or upload
  a runner workspace.
- Do not deploy IAM/WIF before Environment policies and secret/output wiring are
  ready, and do not leave the wildcard after migration as a rollback path.

## Non-Goals And Implementation Boundaries

- No change to the ADR-004-R22 base-image role, base-image PassRole policy,
  guest build logic, image contents, GCE range runtime, or #1666 range-backend
  binding.
- No redesign of application OIDC/Cognito/Identity Platform authentication;
  GitHub Actions OIDC is a separate machine-identity boundary.
- No new application persistence, API/error schema, cloud-provider abstraction,
  identity-policy DSL, image registry, or promotion database.
- No weakening of environment approval, branch protection, action pinning,
  Checkov, TFLint, ADR guard, cleanup, or existing image validation to make the
  trust cutover pass.
- No automatic cloud apply, GitHub Environment mutation, secret write,
  deployment, image validation/promotion, merge, or production cutover in the
  implementation PR. Live settings and IAM/WIF activation remain an explicit
  operator action with readback.
- No broad least-privilege redesign of all deploy permissions. R23 narrows who
  may obtain existing deploy capability; workflow-specific identities in the
  affected image paths are narrowed to their exercised operations.

## Validation Expectations

At minimum, implementation must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
actionlint
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run Terraform fmt/validate and Checkov through the canonical configuration
for every affected root, the AWS IAM and GCP WIF checker suites, deploy-workflow
ADR tests, Packer workflow tests, bootstrap tests when outputs/secrets change,
and reviewed plans for each affected cloud environment. Live verification must
read back the repository OIDC customization, every trusted Environment's branch
policy, the applied AWS trust documents, the GCP provider condition and exact SA
members, and successful protected-ref smoke runs; feature-branch and tag probes
must be denied before cloud authentication.
