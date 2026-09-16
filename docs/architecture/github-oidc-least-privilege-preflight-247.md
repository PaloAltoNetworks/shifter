# GitHub OIDC Least-Privilege Preflight (#247)

Status: pre-implementation guidance

Date: 2026-09-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/247>

Issue #247 is the shipping contract. This is a requirement-free architecture
preflight; it does not change an IAM policy, workflow, AWS account, or Terraform
state.

## Delivered scope (first PR)

Issue #247 carries two threads: the least-privilege scope-down analyzed below,
and the follow-up comment's durable fix: a CI drift-check for the out-of-band
`global/iam` stack. The maintainer selected the **drift-check** for the first
PR: `.github/workflows/iam-drift-check.yml` runs `terraform plan
-detailed-exitcode` against `global/iam` on push to a protected branch and fails
on drift, pinned by the `global-iam-drift-check` guard (ADR-004-R26). It removes
**no** permissions, so the action-set-preservation caution in the follow-up
comment holds. The least-privilege scope-down below (removing `ec2:*`, auditing
wildcards, CloudTrail corroboration) is **deferred future work**; its guardrails
remain the binding design for that later change.

## Decision Boundary

The migrated issue describes an older IAM layout. In the current repository,
`platform/terraform/global/iam/github-oidc.tf` is the canonical owner and
ADR-004-R18 has already consolidated the general deploy role into six attached
category policies. The broad-permission debt remains: the general role still
contains `ec2:*`, overlapping EC2 grants, and several other action wildcards.

The audit must preserve the current principal boundaries rather than rebuild the
old policy layout:

| Principal | Current work | Boundary for #247 |
| --- | --- | --- |
| `github-actions-shifter-${environment}` | Terraform plan/apply/destroy, image publication, ECS/EKS deploy operations, migration/smoke commands, AMI promotion, and (currently) scenario Packer bake | This is the policy being narrowed. Inventory every current caller, but do not retain another principal's actions here. |
| `github-actions-shifter-${environment}-image` | Base-image Packer build, verification, cleanup, and AMI-pointer publication | Preserve ADR-004-R22's exact protected-branch trust, exact PassRole target, and enumerated EC2 actions. Base-image CloudTrail events are not evidence for the general role. |
| Provisioner role receiving `modules/provisioner-iam` | Runtime range instance, network, GWLB/VPN, SSM, and request-owned IAM lifecycle | Preserve this separate runtime boundary. Runtime range-provisioning events are not evidence for GitHub OIDC permissions. |
| Bootstrap/operator AWS identity | Global-IAM creation, policy cutover, and recovery that the deploy role cannot safely perform on itself | Keep global-IAM activation an explicit operator operation through the existing bootstrap/manual surfaces. Do not grant self-administration merely to make rollout convenient. |

`cognito-idp:*` below is an AWS deployment permission; it is not the GitHub
OIDC trust contract or the portal's user-login OIDC flow. Keep those concepts
separate.

## Architecture Decisions And Guardrails

- CloudTrail is corroborating runtime evidence, not an allowlist generator and
  not proof that an unobserved action is unnecessary. The reviewed permission
  set is the union of checked-in Terraform/provider needs, direct AWS CLI and
  Packer calls, create/update/delete and failure-cleanup paths, and observations
  from representative dev/proof/prod runs. An observation window that omitted a
  destroy, cold create, rotation, promotion, or failed-build cleanup cannot
  justify deleting that path's actions.
- Attribute events to the exact assumed role before counting them. Do not merge
  events from the base-image role, provisioner ECS/IRSA role, EC2 instance
  profiles, service-linked roles, or an operator profile into the general deploy
  role's evidence. AWS service calls made after the deploy role passes a runtime
  role are evidence for the passed role, not for the caller's future policy.
- General-role sessions need bounded, run-correlatable names at every existing
  `aws-actions/configure-aws-credentials` call. Reuse the base-image convention:
  a fixed purpose/job prefix plus `github.run_id` and `github.run_attempt`.
  Session names must not contain secrets, free-form refs, user input, or an ARN.
  A generic shared session name makes CloudTrail attribution ambiguous and must
  not be treated as complete evidence.
- Keep policy JSON in the existing Terraform `jsonencode(...)` documents. Do
  not add a YAML permission schema, generated policy file, external policy DSL,
  or a second deploy-role module. CloudTrail-derived tooling may normalize an
  audit report, but it must not become a second authority for the shipped IAM
  document.
- Every EC2 action granted to the general role must have one policy owner and
  one documented purpose. Remove `ec2:*` and overlapping wildcard families;
  do not leave a broad statement as a compatibility fallback. ADR-004-R18's
  attachment cap and ADR-004-R19's 6,144-character document cap still apply. If
  literal action enumeration creates size pressure, repartition non-EC2
  categories by real ownership within those limits rather than restore a
  wildcard or hide permissions in role inline policies.
- Separate EC2 statements by authorization shape. Read/list APIs that require
  `Resource = "*"` stay action-enumerated and isolated. Create operations use
  supported request-tag/create-action conditions. Existing-resource mutation
  uses region/account ARNs, deterministic namespaces, and ownership resource
  tags where supported. `RunInstances` dependent resources (image, instance,
  volume, network interface, subnet, security group, key pair, and PassRole)
  are evaluated independently; a scope that covers only the resulting instance
  ARN is not sufficient.
- Reuse the established ownership vocabulary for Terraform-managed platform
  resources: `Project=shifter`, `Environment=<env>`, and
  `ManagedBy=terraform`. Before an IAM condition depends on a tag, prove every
  affected create path sends the exact fixed tag and that later tag mutation
  cannot mark an arbitrary account resource as owned. Do not copy the runtime
  provisioner's distinct `shifter:system` / `shifter:environment` tag contract
  into the deploy role, and do not apply Terraform ownership conditions to
  Packer resources tagged `ManagedBy=packer` or `Project=polaris-bake`.
- Review all action wildcards in the canonical file, not only `ec2:*`. The
  current audit surface includes EC2 pattern wildcards plus `ecs:*`,
  `elasticloadbalancing:*`, `acm:*`, `ecr:*`, `s3:*`, `cognito-idp:*`,
  `sqs:*`, `firehose:*`, and `kms:ReEncrypt*`. Each must be enumerated or
  carry a service-specific, reviewed justification. Split APIs that require a
  wildcard resource from APIs that support an ARN or condition; `Resource =
  "*"` is not acceptable merely because another action in the statement needs
  it.
- Do not misclassify permissions-boundary semantics as a principal wildcard.
  `ci_role_permissions_boundary` intentionally has an Allow `Action = "*"` /
  `Resource = "*"` ceiling followed by IAM denies; the boundary grants nothing
  on its own. Its `iam:*` is a deny. Preserve its mandatory-boundary conditions
  and tamper denies unless a separate reviewed boundary change proves an
  equivalent shape.
- Purpose separation is preferred to unioning unrelated capabilities into the
  general role. The base-image split is complete. The scenario-bake caller's
  use of the general role is already identified by ADR-004-R23 as separate-
  principal debt; it must not justify retaining general `ec2:*`. AMI promotion
  likewise needs only its exact read/share/copy/publish actions. If a caller
  cannot move to its purpose identity in this issue, retain only its enumerated
  actions and record the residual boundary explicitly rather than claiming the
  role is purpose-isolated.
- A read/query failure means unknown, never unused or clean. Follow
  `account_recovery.AwsQueryError`: distinguish an empty successful result from
  authorization failure, throttling, malformed output, wrong region/account,
  or an incomplete time window. Fail the audit closed and report the safe phase
  and action family without printing raw AWS response bodies.
- Raw CloudTrail events are operationally sensitive. They may expose account
  identifiers, role session identifiers, resource names, request parameters,
  repository/run metadata, and error context. Keep raw downloads in
  `RUNNER_TEMP`, `/tmp`, or controlled operator storage; do not commit them or
  upload them as public Actions artifacts. A repository record, if needed,
  contains only normalized action names, principal purpose, environment,
  covered lifecycle phase, bounded timestamps/run IDs, and disposition.
- Narrowing is a fail-closed rollout. Review plans separately for dev, proof,
  and prod; exercise create/update/destroy and cleanup before advancing; and do
  not run unrelated deploys during the global-IAM cutover. AccessDenied must
  name the service/action and phase without dumping provider debug logs,
  tfvars, state, credentials, raw CloudTrail events, or complete IAM documents.
- The result is incomplete without a regression gate. Extend the existing
  OIDC/IAM semantic checker surface so the eliminated action wildcards,
  duplicate EC2 ownership, required statement conditions, and purpose-role
  boundaries cannot return. Keep focused positive and negative tests and
  pre-commit/CI parity. A new or changed architecture guard requires the matching
  ADR registry/enforcement update; do not encode the rule only in workflow YAML.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| General OIDC role and policy documents | `platform/terraform/global/iam/github-oidc.tf` | Narrow the existing role and category policies in place; preserve `jsonencode`, environment/account/region derivation, tags, outputs, and the dedicated image role. |
| Category and quota governance | ADR-004-R18/R19 and `scripts/check_tf_iam_role_naming/` | Keep no more than six attachments, policy documents below the repository limit, IAM role namespaces, attachment allowlists, EKS boundary, image-role trust, and exact image PassRole checks. |
| EC2 statement shapes | `platform/terraform/modules/provisioner-iam/main.tf` and `scripts/check_tf_iam_ec2_scope/` | Reuse the read/create/existing-mutation/RunInstances separation and tag-aware negative-test style. Do not copy runtime role actions or its tag vocabulary into the deploy role. |
| ELBv2 statement shapes | `platform/terraform/modules/provisioner-iam/main.tf`, `platform/terraform/modules/portal/eks/load_balancer_controller_iam.tf`, and `scripts/check_tf_iam_elb_scope/` | Reuse action enumeration, create/request tags, existing-resource tags, ARN namespaces, and isolated describe statements when narrowing the general ELB grant. |
| Read-only AWS inspection and reporting | `scripts/bootstrap/account_recovery.py` plus `bootstrap_core.run_cmd` and logging helpers | Use argv arrays, the existing redactor, explicit account/environment/region/profile inputs, typed query failure, and bounded value-free reports. Do not stream raw CloudTrail JSON or invent a parallel command/error framework. |
| AWS environment/secret mapping | `scripts/bootstrap/preflight.py`, `scripts/bootstrap/aws_bootstrap.py`, `scripts/bootstrap/aws_env_destroy.py`, `scripts/terraform/render_aws_backend_configs.py`, and `docs/dev/deploy-secrets.md` | Preserve the closed dev/proof/prod mapping, explicit `AWS_ROLE_ARN[_DEV|_PROOF]` selection, fail-loud missing values, backend validation, and credential-source behavior. |
| Credentialed caller inventory | `.github/workflows/{_core.yml,_range.yml,_shifter-engine.yml,_shifter-platform.yml,aws-env-destroy.yml,packer.yml,packer-promote.yml}` with `deploy.yml` as router | Account for every general-role assumption, including both teardown sessions, all plan/apply/build/deploy/verify/smoke jobs, scenario bake, and each dev/prod promotion role switch. |
| Packer contracts | `shifter/packer/*.pkr.hcl`, `shifter/packer/tests/test_packer.py`, and ADR-004-R22/R23 | Preserve builder/run tag alignment, encryption/verification-before-publish, bounded cleanup, protected provenance, and the dedicated base-image role. |
| Terraform configuration and state | Root variables/tfvars under `platform/terraform/environments/{dev,proof,prod}/`, `platform/terraform/validation-inventory.yaml`, global-IAM backend files, and provider lockfiles | Keep environment inputs typed, root/provider ownership registered, global IAM in its existing backend key, and live values outside tracked examples. |
| Security policy and repository gates | `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, `.pre-commit-config.yaml`, `.github/workflows/_quality.yml`, and `scripts/adr_guard/` | Keep Checkov blocking, local/CI semantics aligned, exceptions scoped/dated/truthful, action pins intact, and guardrail documentation synchronized. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **GitHub authorization and AWS OIDC trust.** Continue using
   `aws-actions/configure-aws-credentials` with job-local `id-token: write` and
   no static AWS keys. Preserve exact `aud = sts.amazonaws.com`. ADR-004-R23's
   binding target is an exact protected-branch/environment subject inventory,
   not `repo:...:*`; permission reduction must not broaden that trust or treat a
   workflow-local ref check as the external authorization boundary.
2. **Environment and workflow input shape.** Environment selection remains the
   closed `dev|proof|prod` mapping in Terraform, bootstrap preflight, backend
   rendering, and explicit workflow case statements. Role ARNs come only from
   the existing environment secrets, never a caller-supplied role input or
   dynamically evaluated secret name. Free-form refs and resource identifiers
   do not enter session names or policy resources.
3. **Terraform configuration validation.** The existing root variables,
   `tags` maps, provider/module locals, and committed example plus gitignored
   overlay convention remain authoritative. If ownership tags become an IAM
   condition, validate or derive their exact security-sensitive keys at their
   current owner; do not add a second environment/tag schema in an audit tool.
4. **IAM evaluation.** The identity policy, CI-created-role permissions
   boundary, PassRole service/resource constraints, managed-policy attachment
   allowlists, request/resource tag conditions, and OIDC trust all evaluate
   independently. A passing resource ARN does not compensate for broad
   PassRole, arbitrary retagging, or wildcard trust. Preserve explicit denies
   and exact purpose-role boundaries.
5. **Secret and identifier handling.** OIDC tokens, STS credentials, tfvars,
   backend values, private Packer inputs, and raw CloudTrail events stay in the
   incumbent secret/environment/temp-file channels. Do not commit or summarize
   live account IDs, role ARNs, state bucket names, VPC/subnet IDs, credential
   material, or request payloads. ADR-004-R14 and gitleaks remain backstops, not
   permission to log first and redact later.
6. **Host/OS exposure.** Cloud/AWS commands use argv arrays and inherited
   credential environments or `credential_source = Environment`; credentials,
   policies, event JSON, and secret-bearing filters never appear in process
   argv. Keep shell tracing and environment dumps off. Temporary audit data is
   owner-readable, run-scoped, removed after summarization, and never left in a
   self-hosted runner workspace.
7. **Error and observability envelope.** Reuse bounded bootstrap reports and
   workflow `::error::`/step-summary conventions. Log safe environment,
   principal purpose, workflow/job/run/attempt, lifecycle phase, AWS service and
   action, and disposition. Suppress tokens, raw claims, raw provider responses,
   tfvars/state, policy bodies, and CloudTrail request/error payloads. Cleanup
   failure remains separately visible from the primary failure.
8. **Persistence and rollout.** Terraform state remains authoritative in the
   existing global-IAM backend. CloudTrail evidence is an audit input, not
   application persistence. Policy attachment/address changes must preserve
   the existing `moved`-block migration contract and avoid quota spikes or
   temporary broad overlap. The deploy role must not gain permission to mutate
   its own trust or policies for self-service rollout.
9. **Repository enforcement.** Terraform fmt, backendless root init/validate,
   TFLint, Checkov, the OIDC/IAM and service-specific checker suites,
   workflow/Packer/bootstrap tests, actionlint for workflow changes, action SHA
   pinning, quality-path ownership, and the full ADR guard must all see their
   applicable changes.

## Whole-Repository Inventory In Scope

- Policy/state owner: `platform/terraform/global/iam/**`, including all three
  environment tfvars/backend configurations and the dedicated image role.
- AWS infrastructure demand: `platform/terraform/environments/{dev,proof,prod}`
  and the AWS modules they compose. The checked-in `aws_*` resource estate is
  the static upper-bound input to the deploy-role audit.
- Runtime contrast, not deploy-role grant source:
  `platform/terraform/modules/provisioner-iam/**`, its engine-provisioner/EKS
  attachments, and the runtime Terraform under
  `shifter/engine/provisioner/terraform/**`.
- Direct workflow demand: all credentialed AWS workflows named in the caller
  inventory above, including CLI calls outside Terraform and failure cleanup.
- Packer demand: `shifter/packer/**`, including scenario inputs, builder/run
  tags, verification, promotion, and tests.
- Operator/cutover surfaces: `scripts/bootstrap/**`,
  `scripts/terraform/render_aws_backend_configs.py`, `scripts/iam-deploy.sh`,
  deployment/teardown/AMI runbooks, GitHub environment secrets, AWS STS, IAM,
  CloudTrail, and the self-hosted runner filesystem/process environment.
- Guardrails: ADR-004-R11/R14/R15/R18/R19/R22/R23/R25,
  `docs/adr/{index.yaml,exceptions.yaml}`, `scripts/check_tf_iam_*`,
  `scripts/adr_guard/**`, `.pre-commit-config.yaml`,
  `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml`,
  `platform/terraform/.checkov.yaml`, `.tflint.hcl`, and the Terraform
  validation inventory.

The checked-in Prisma Cloud connector templates under `platform/cloudformation`
contain CloudTrail infrastructure but are vendor artifacts, not the CI policy
audit boundary. Do not reuse or edit them for #247.

## Extensibility Seam

The primary seam is **principal purpose plus single policy ownership**, not an
AWS-service wildcard and not a new permission DSL. A future deploy-managed AWS
capability adds its explicit actions to exactly one existing category, with its
resource/condition shape and caller evidence beside the incumbent Terraform and
checker tests. A future non-deploy capability receives a purpose role following
the existing image-role output/secret/session-name convention instead of
growing the general role.

The observability parameter is a fixed, validated purpose/job prefix in the
STS role-session name, followed only by GitHub's run ID and attempt. That seam
lets a future caller produce attributable CloudTrail evidence without changing
the IAM document or inventing another audit schema.

## Gotchas And Anti-Patterns

- Do not use CloudTrail activity from the wrong principal, account, region, or
  environment, and do not count AWS service-on-behalf-of events as caller
  permissions.
- Do not infer least privilege from a steady-state apply. Terraform refresh and
  plan need reads; first deploy needs creates and service-linked-role paths;
  updates, rotation, destroy, interrupted Packer, teardown, and recovery need
  different actions.
- Do not feed raw events into policy generation and auto-apply the result.
  Generated policies omit unobserved legitimate paths and preserve accidental
  activity without architectural review.
- Do not replace `ec2:*` with cosmetically narrower families such as
  `ec2:Describe*`, `ec2:*Vpc*`, or `ec2:*SecurityGroup*` without enumerating and
  reviewing the matched actions. A wildcard suffix is still future permission
  expansion when AWS adds an API.
- Do not ban every `Resource = "*"` mechanically. Some catalog/list/create APIs
  require it. Isolate those actions, enumerate them, add supported conditions,
  and keep a precise residual-risk explanation.
- Do not authorize ownership by tag while also allowing arbitrary
  `CreateTags`/`DeleteTags` against account-wide resources. Creation-time tags
  and mutation of already-owned resources are separate statements.
- Do not merge the dedicated base-image policy back into the general role or
  widen its exact PassRole target. Do not use runtime provisioner policy actions
  as evidence that GitHub needs them.
- Do not keep scenario Packer or promotion actions in the deploy role under the
  label “Terraform infrastructure management.” If temporarily co-located, keep
  their exact actions/statements visibly distinct so a purpose-role cutover does
  not require rediscovering them.
- Do not change application Cognito/OIDC configuration, portal authentication,
  runtime IAM roles, GCP WIF, database schemas, service/repository boundaries,
  or logging frameworks to solve a deployment-principal policy issue.
- Do not add another generic exception hierarchy. AWS query failures use the
  bootstrap inspection pattern; static policy violations use the existing
  checker `Violation` pattern; workflow failures use `::error::` and non-zero
  exit.
- Do not silently preserve the current “rapid development” Checkov skips and
  exception prose after their facts change. The current
  `aws-dev-bootstrap-inline-admin` exception describes an admin-equivalent
  inline policy that the canonical file no longer contains; reconcile or remove
  stale rationale as the final residual policy becomes known.
- Do not grant the general role access to `cloudtrail:LookupEvents` merely so it
  can audit itself. Run operational evidence collection under a separate
  read-only operator/audit identity. A PR check remains credential-free and
  validates the committed policy shape.
- Do not rely on the deploy role to destroy or rewrite itself. The current
  teardown includes `global/iam`, while the scoped role name is outside its own
  `shifter-*` IAM management namespace. Preserve the non-self-admin boundary and
  make the operator-owned finalization/cutover behavior explicit.

## Non-Goals

- No implementation of the policy reduction, CloudTrail query, regression
  checker, role-session naming, purpose-role migration, or live AWS rollout in
  this preflight.
- No new application API, DTO, database/persistence schema, shared exception
  hierarchy, logging framework, cloud-provider abstraction, or policy language.
- No redesign of the runtime range provisioner, EKS workload identities,
  portal Cognito login, GCP Workload Identity, Packer image contents, or
  Terraform backend layout.
- No modification of vendor CloudFormation CloudTrail resources and no new
  repository copy of raw CloudTrail evidence.
- No permission expansion to make stale workflows pass. A newly discovered
  action is admitted only when a checked-in caller/lifecycle path and the
  narrowest supported resource/condition shape justify it.

## Validation Boundary For The Later Implementation

The eventual implementation is not complete until the applicable repository
gates pass, including:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

It must also run Terraform fmt and the inventory-driven backendless validation
for affected roots, Checkov through the canonical config, focused IAM checker
tests, Packer/bootstrap/workflow semantic tests for changed callers, and
`actionlint` when a workflow changes. Live CloudTrail review and staged
dev/proof/prod readback are operational acceptance evidence, not substitutes for
the credential-free repository gates.
