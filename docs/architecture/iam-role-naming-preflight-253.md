# IAM Role Naming Preflight (#253)

Status: pre-implementation guidance

Date: 2026-06-25

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/253>

This note records the repository-wide guardrails for standardizing AWS IAM role
names so the GitHub Actions OIDC deploy role can be scoped to Shifter-owned IAM
resources. It is not an implementation plan.

## Scope Boundary

The issue is an AWS IAM least-privilege hardening change. The target outcome is
that deploy-managed IAM roles and instance profiles use a consistent
`shifter-${environment}-${component}-${purpose}` name shape, allowing the
GitHub Actions OIDC role to replace broad IAM permissions with `shifter-*`
resource scopes and a managed-policy attachment allowlist.

Keep the change in the existing Terraform, bootstrap, workflow, and guardrail
surfaces. Do not redesign runtime services, cloud-provider abstractions,
secret hydration, Django auth, database contracts, range provisioning behavior,
or logging frameworks to satisfy this issue.

## Architecture Decisions

- Treat role naming as an IAM authorization boundary, not cosmetic cleanup.
  The naming contract only helps if every role and instance profile that the
  deploy role may create, update, pass, attach, or delete is inside the same
  explicit namespace.
- Do not blindly change generic `name_prefix` values without reviewing the
  blast radius. In the AWS environment roots, `local.name_prefix` also feeds
  non-IAM resource names, CloudWatch log group names, KMS aliases/tags,
  buckets, alarm dimensions, SSM paths, and operator-facing outputs. If the
  implementation changes `name_prefix`, it is a broader infrastructure rename.
  If only IAM names need to move, add the smallest IAM-specific name seam in the
  module or root that owns those IAM resources.
- Include instance profiles in the naming boundary when the OIDC policy scopes
  `iam:CreateInstanceProfile`, `iam:AddRoleToInstanceProfile`,
  `iam:RemoveRoleFromInstanceProfile`, or `iam:DeleteInstanceProfile`. Role
  names alone are not enough.
- The deploy role itself needs special handling. If it remains outside
  `shifter-*`, the deploy role cannot manage itself through a `shifter-*`
  resource allow. If it is renamed into the `shifter-*` namespace, add an
  explicit self-management deny or exact-resource exclusion so a compromised
  workflow cannot mutate its own trust or permissions.
- Build the managed-policy attachment allowlist from policies the repo actually
  attaches. Current first-party Terraform uses at least:
  `AmazonSSMManagedInstanceCore`,
  `service-role/AmazonECSTaskExecutionRolePolicy`,
  `service-role/AWSLambdaBasicExecutionRole`, and
  `service-role/AmazonRDSEnhancedMonitoringRole`. Do not add speculative
  policies from the issue text unless a checked-in Terraform attachment or an
  intentional new attachment requires them.
- Do not overstate the security benefit of restricting
  `iam:AttachRolePolicy`. Most platform modules use inline
  `aws_iam_role_policy` resources, so `iam:PutRolePolicy`,
  `iam:DeleteRolePolicy`, and related role-management actions need their own
  scoped treatment. Attachment allowlists do not prevent inline-policy
  escalation by themselves.
- Preserve the existing SCP-aware inline-policy precedent. The repo already
  records that some AWS organizations deny `iam:AttachRolePolicy`; if a target
  account still has that SCP, the implementation must keep or document an
  inline equivalent rather than assuming managed-policy attachment works.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #253 |
| --- | --- | --- |
| GitHub OIDC role ownership | `platform/terraform/global/iam/github-oidc.tf` | Replace or narrow the existing admin-equivalent inline policy here; do not add a second deploy-role module or policy generator. |
| Bootstrap role naming and GitHub secret wiring | `scripts/bootstrap/deploy.py`, `scripts/bootstrap/tests/test_deploy.py`, `scripts/bootstrap/README.md`, `docs/dev/deploy-secrets.md` | Keep generated role names, Terraform outputs, and `AWS_ROLE_ARN*` GitHub secrets in agreement. |
| AWS workflow role assumption | `.github/workflows/{_core.yml,_range.yml,_shifter-engine.yml,_shifter-platform.yml,deploy.yml,packer.yml,packer-promote.yml,polaris-scenario-bake.yml}` | Continue using `aws-actions/configure-aws-credentials` and existing OIDC secrets; do not add long-lived AWS keys. |
| Environment naming inputs | `platform/terraform/environments/{dev,prod,proof}/{portal,range}/main.tf` | Account for `proof` explicitly or document why it is out of scope; do not silently hard-code only dev/prod when workflows expose proof. |
| IAM role resources | `platform/terraform/modules/{portal/ec2,portal/cognito,portal/ctfd,portal/rds,portal/vpc,range/vpc,engine-provisioner,guacamole,log-aggregation}` | Rename or exempt existing IAM roles and instance profiles at their owning module boundary. |
| IAM hardening checks | `scripts/check_tf_iam_ec2_scope`, `scripts/check_tf_iam_elb_scope`, `scripts/check_tf_kms_secrets_grant` | If regression coverage is added, follow the focused repo-native Python checker pattern and wire it into both pre-commit and `_quality.yml`. |
| Terraform security policy | `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, ADR-004-R11 | Update exception text if the GitHub OIDC admin-equivalent exception no longer describes the accepted risk. |

## Cross-Cutting Layers

- GitHub auth surface: role assumption stays through GitHub OIDC and
  `aws-actions/configure-aws-credentials`; no static AWS access keys, broader
  trust subject, or `pull_request_target` credential path should be added.
- IAM policy gate: scoped allows must cover role, instance-profile, pass-role,
  inline-policy, managed-policy attachment, and delete/update operations that
  Terraform actually performs. Use explicit denies or exclusions for deploy
  role self-management if the deploy role shares the `shifter-*` prefix.
- Managed-policy attachment gate: `iam:AttachRolePolicy` must require both a
  `role/shifter-*` resource scope and an `iam:PolicyArn` allowlist derived from
  checked-in attachments.
- Inline-policy gate: `iam:PutRolePolicy` and `iam:DeleteRolePolicy` remain a
  separate escalation surface. Scope them to Shifter-owned roles and document
  any residual risk that needs a future permissions-boundary issue.
- PassRole gate: `iam:PassRole` should be role-scoped and service-constrained
  with `iam:PassedToService` for the services this repo actually uses, such as
  EC2, ECS tasks, Lambda, VPC Flow Logs, CloudWatch Logs, Firehose, and RDS
  monitoring.
- Secret-handling surface: role ARNs and policy ARNs are configuration values,
  not secret material, but workflow and bootstrap changes must still avoid
  printing GitHub secret bodies, rendered tfvars, provider credentials, or real
  account-specific identifiers.
- Env-binding shape: Terraform variables and `AWS_ENVIRONMENTS` in
  `scripts/bootstrap/deploy.py` are the environment contract. Keep naming
  derived from those inputs rather than copying string literals into multiple
  roots.
- Terraform state and persistence: IAM role and instance-profile `name`
  changes are replacement-prone. Terraform `moved` blocks only move state
  addresses; they do not make an AWS IAM name mutable. Review per-root plans
  for forced replacement, attachment churn, launch-template/profile churn, and
  downtime.
- Observability surface: generic `name_prefix` changes can alter CloudWatch log
  names, alarm names, metric dimensions, and workflow comments that assume
  `<environment>-portal`. Keep those changes intentional and tested.
- Config validators: implementation must pass Terraform fmt/validate, TFLint,
  Checkov's canonical config, ADR guard, and actionlint when workflows change.
  Guardrail-file edits must keep ADR documentation in sync.
- OS/process exposure: policy JSON may be passed to AWS CLI/Terraform as
  non-secret configuration, but credentials and generated secret payloads must
  not appear in argv, shell tracing, plan comments, or workflow logs.
- Error and observability envelope: workflow failures should use bounded
  GitHub Actions annotations naming the missing secret, invalid environment, or
  policy-shape violation. Do not dump full credentials, tfvars bodies, or
  provider debug output.

## Extensibility

The seam is the IAM naming/policy namespace, not generic resource naming. Keep a
single local or module input for the IAM role prefix where a module's existing
`name_prefix` is too broad. Keep the managed-policy attachment allowlist in one
Terraform local or variable near the GitHub OIDC policy so adding a future
first-party attachment is a list edit plus test update, not copied JSON across
workflow or bootstrap code.

## Gotchas And Anti-Patterns

- Do not conflate component and purpose names. `portal`, `range`,
  `guacamole`, `engine-provisioner`, `log-aggregation`, and `github-actions`
  are different components with different trust policies.
- Do not treat `shifter-*` as safe if it includes the deploy role and there is
  no self-management deny.
- Do not use `AttachRolePolicy` allowlisting as a substitute for handling
  inline policies, pass-role, instance profiles, trust-policy updates, or
  permissions boundaries.
- Do not rename non-IAM resources as collateral damage unless the issue
  deliberately accepts the migration and validation cost.
- Do not add a new IAM policy schema, exception hierarchy, code generator, or
  Terraform framework for this narrow hardening change.
- Do not widen Checkov skips, remove ADR exceptions without replacing the
  actual risk record, or weaken workflow path filters to get the Terraform
  change through CI.
- Do not commit real AWS account IDs, role ARNs, bucket names, or tfvars values
  while updating docs, tests, or examples.

## Non-Goals

- No redesign of the engine provisioner, portal runtime, Guacamole, Cognito,
  range placement, Kubernetes/GCP infrastructure, or Django auth/session model.
- No new public API, DTO, persistence schema, validation framework, logging
  framework, or cloud-provider abstraction.
- No permissions-boundary rollout unless explicitly split into this issue's
  implementation contract; it remains a likely follow-up for closing inline
  policy escalation.
- No broad cleanup of workshop/demo/global IAM unless those roles are managed by
  the same GitHub Actions deploy role and must be inside or outside the new
  scope intentionally.

## Validation Expectations

At minimum, the implementation should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run `terraform fmt` and `terraform validate` for touched roots/modules,
`actionlint` if workflows change, bootstrap tests if `scripts/bootstrap/**`
changes, and any new or updated `scripts/check_tf_*` checker tests.
