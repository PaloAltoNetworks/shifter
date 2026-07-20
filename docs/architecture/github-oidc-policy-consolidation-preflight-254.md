# GitHub OIDC Policy Consolidation Preflight (#254)

Status: pre-implementation guidance

Date: 2026-06-25

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/254>

This note records the repository-wide guardrails for consolidating the GitHub
Actions OIDC role's managed IAM policies below AWS's 10-managed-policy hard
limit. It is not an implementation plan.

## Scope Boundary

The issue is an AWS IAM policy-layout refactor for the existing GitHub Actions
OIDC deploy role in `platform/terraform/global/iam/github-oidc.tf`. The target
outcome is fewer managed-policy attachments while preserving the current trust
boundary, least-privilege constraints, and Terraform workflow behavior.

Keep the change inside the existing global IAM Terraform, docs, tests, and
repo-native guardrails unless validation proves a small update is required. Do
not redesign deployment workflows, bootstrap identity, runtime roles, Terraform
state layout, portal auth, cloud-provider abstractions, secret hydration, or
logging frameworks for this issue.

## Architecture Decisions

- Treat this as policy packing, not permission expansion. Each service action
  should move to exactly one consolidated policy by ownership category; do not
  add wildcard actions, wildcard resources, new services, or new principals just
  because a category is being renamed.
- Preserve the GitHub OIDC trust contract: `aud = sts.amazonaws.com`,
  `sub = repo:${var.github_org}/${var.github_repo}:*`, and the same
  `aws-actions/configure-aws-credentials` workflow assumption path. No static
  AWS keys or broader `pull_request` credential surface belong in this change.
- Preserve the CI-created-role boundary. The standalone
  `aws_iam_policy.ci_role_permissions_boundary`, the `iam:CreateRole`
  `iam:PermissionsBoundary` condition, the `role/shifter-*` IAM resource scope,
  the `iam:AttachRolePolicy` allowlist, and the `iam:PassedToService`
  constraints remain security controls, not grouping details.
- Consolidate into domain policies with stable category names such as compute,
  networking, data, security, and management. The exact statements can move
  between those groups only when the target category owns the service surface.
  Avoid a miscellaneous bucket that becomes the next hard-limit problem.
- Keep policy JSON in Terraform `jsonencode(...)` using the current inline
  statement style. Do not introduce a policy generator, duplicate schema,
  external template language, or second IAM abstraction for this narrow refactor.
- Leave headroom intentionally. A successful consolidation should end below the
  AWS 10-attachment limit with spare slots for future domains; if a category
  approaches the 6,144-character managed-policy size limit, split by real
  domain ownership instead of falling back to role inline policies.
- The migration must account for Terraform replacement semantics. Renaming
  `aws_iam_policy` resources changes policy ARNs; attaching new policies,
  detaching old policies, and deleting old policies must be reviewed in plan
  output for both permission gaps and over-permissive overlap during rollout.
- Reconcile the environment contract while touching the file. The repository
  already has `dev.tfvars`, `prod.tfvars`, and `proof.tfvars` plus workflow
  support for `proof`; Terraform variable validation must not silently exclude a
  supported environment.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #254 |
| --- | --- | --- |
| GitHub OIDC role ownership | `platform/terraform/global/iam/github-oidc.tf` | Consolidate the existing policies here; do not add a second deploy role, module, or generator. |
| IAM role namespace and attachment constraints | `scripts/check_tf_iam_role_naming/check_tf_iam_role_naming.py`, `docs/architecture/iam-role-naming-preflight-253.md` | Keep `role/shifter-*`, `iam:PolicyArn` allowlisting, and the required AWS-managed policy names intact. |
| Bootstrap and role output wiring | `scripts/bootstrap/deploy.py`, `scripts/bootstrap/terraform_backend.py`, `docs/dev/deploy-secrets.md` | Keep `github_actions_role_arn`, backend stack key `global/iam`, and `AWS_ROLE_ARN*` secret guidance compatible. |
| AWS workflow role assumption | `.github/workflows/{_core.yml,_range.yml,_shifter-engine.yml,_shifter-platform.yml,deploy.yml}` | Continue using OIDC with `id-token: write`; do not add long-lived credential inputs or PR deploy access. |
| Terraform security policy | `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, ADR-004-R11 | Existing Checkov skips and exception text must still describe the residual risk after consolidation. |
| Local and CI validation | `.pre-commit-config.yaml`, `.tflint.hcl`, `.github/workflows/_quality.yml`, `scripts/adr_guard/adr_guard.py` | Keep Terraform fmt/validate/TFLint/Checkov/ADR guard coverage aligned; new guardrails must be local and CI wired. |
| Manual/global IAM deploy path | `scripts/iam-deploy.sh`, `scripts/bootstrap/deploy.py` | Use existing env/profile/backend conventions; do not create a parallel manual apply script. |

## Cross-Cutting Layers

- Auth surface: GitHub Actions assumes the same OIDC role through the existing
  `AWS_ROLE_ARN*` secrets and `aws-actions/configure-aws-credentials`. The
  design satisfies this layer by leaving the trust policy and workflow
  credential flow unchanged.
- IAM policy gate: Terraform-managed AWS access still flows through managed
  policies attached to `aws_iam_role.github_actions`. The design satisfies this
  layer by moving existing statements into fewer policies without weakening
  resource scopes, conditions, permission boundaries, or service constraints.
- IAM role-naming validator: `check_tf_iam_role_naming.py` statically checks
  the OIDC file for legacy role patterns, `role/shifter-*`, and the managed
  policy attachment allowlist. The design satisfies this layer by preserving
  those literals and updating tests only if the checker gains equivalent
  category-count assertions.
- Checkov and ADR exception layer: first-party Terraform remains blocking under
  `platform/terraform/.checkov.yaml` and ADR-004-R11. The design satisfies this
  layer by retaining inline skip comments only where the accepted risk still
  applies and updating `docs/adr/exceptions.yaml` if the reason no longer
  matches the consolidated policy shape.
- Terraform config shape: `var.environment`, `var.github_org`,
  `var.github_repo`, `var.aws_region`, provider default tags, and the S3 backend
  config are the binding inputs. The design satisfies this layer by deriving
  policy names and ARNs from those inputs, not duplicated literals.
- Secret-handling surface: role ARNs and policy ARNs are configuration, but
  rendered tfvars, AWS credentials, and account identifiers remain sensitive in
  logs. The design satisfies this layer by avoiding shell tracing, credential
  echoing, and committed account-specific examples.
- OS/process exposure: Terraform plans and AWS CLI calls may expose policy
  names and ARNs but must not pass secrets in process argv. The design satisfies
  this layer by keeping secret material in existing GitHub secrets, environment
  variables, or backend config files and not adding new CLI-secret arguments.
- Error/log envelope: workflow failures should identify missing environment
  inputs, Terraform validation failures, or policy-size/attachment-limit
  violations without dumping full tfvars, credentials, or provider debug logs.
  Reuse the existing `::error::` pattern in workflows if workflow code changes.
- Persistence/state layer: global IAM state stays in the existing `global/iam`
  backend key. The design satisfies this layer by changing Terraform resources
  in place or with reviewed state moves/imports only when necessary; do not
  create a new state root for the same role.

## Extensibility Boundary

The seam is a single category-to-statements grouping inside
`github-oidc.tf`. Keep category names and any policy-count assertion close to
that Terraform resource set so a future service such as Budgets, Scheduler, or
another deploy-managed AWS domain is added by choosing one category and adding
one statement, not by editing workflows, bootstrap scripts, docs, and multiple
copied policy schemas.

If policy-size pressure appears, split by service-domain ownership with a
documented category name rather than using inline role policies. Inline policies
consume a different AWS quota and reduce auditability; they are not the normal
escape hatch for this issue.

## Gotchas And Anti-Patterns

- Do not blindly follow the migrated issue's old policy names. The current file
  uses `lambda_ops`, not `lambda_sfn`, and the current service list is the
  source of truth.
- Do not co-locate unrelated permissions because they happen to fit under the
  6,144-character policy limit. Category boundaries are the future audit model.
- Do not broaden `secretsmanager`, `kms`, `iam`, `ec2`, `ecs`, `rds`, or
  `cognito` permissions while moving statements. Consolidation should be
  diffable as a structural move, not a privilege grant.
- Do not lose Checkov skip comments by moving only policy bodies and leaving
  accepted-risk documentation behind. Existing skips and ADR exceptions must
  still point to the actual risk.
- Do not treat `iam:AttachRolePolicy` allowlisting as the only IAM escalation
  control. Inline-policy actions, permissions boundaries, `PassRole`, and role
  update/delete actions remain distinct surfaces.
- Do not add a second source of environment truth. `proof` support, if retained,
  belongs in the same variable validation and tfvars/workflow conventions as
  `dev` and `prod`.
- Do not commit real AWS account IDs, live role ARNs, state bucket names, plan
  files, `.terraform/` output, or rendered tfvars while validating the global
  IAM stack.

## Non-Goals

- No redesign of GitHub workflow routing, protected environment gates, reusable
  workflow interfaces, or deploy image identity.
- No new public API, DTO, persistence schema, exception hierarchy, validation
  framework, logging framework, or cloud-provider abstraction.
- No least-privilege expansion beyond preserving or tightening existing
  statements during consolidation.
- No migration of runtime IAM roles, engine-provisioner policies, portal/range
  modules, GCP Workload Identity, Cognito portal auth, or bootstrap account
  creation unless a compatibility check proves a minimal doc/test update is
  required.

## Validation Expectations

At minimum, the implementation should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run `terraform fmt` and `terraform validate` for
`platform/terraform/global/iam`, `terraform plan` for every supported global
IAM environment whose backend is available, `scripts/check_tf_iam_role_naming`
if the OIDC file changes, and Checkov through the existing pre-commit/CI path.
