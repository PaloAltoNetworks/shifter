# ELB IAM Scope Preflight (#46)

Status: implemented (see `aws_iam_role_policy.gwlb` in
`platform/terraform/modules/engine-provisioner/iam.tf` and the regression
checker at `scripts/check_tf_iam_elb_scope/`).

Tracking issue: GitHub #46, migrated from PaloAltoNetworks/shifter#56.

This note records the repository-wide guardrails for narrowing the engine
provisioner's ELBv2 permissions. It is retained as the binding design record
for the static checker that pins the implementation.

## Scope Boundary

The issue is an IAM least-privilege repair for the engine-provisioner ECS task
role. The implementation should stay focused on
`platform/terraform/modules/engine-provisioner/iam.tf` unless a validation or
documentation update is needed to keep the guardrails honest.

Do not change runtime provisioning behavior, task-definition environment
variables, secret hydration, database contracts, SNS events, or cloud-provider
abstractions to satisfy this issue.

## Architecture Decisions

- Split ELBv2 read/list APIs from mutable management APIs. Keep
  `Resource = "*"` only where the AWS ELBv2 service authorization table does not
  support resource-level permissions for the action.
- Prefer enumerated `Describe...` actions over `Describe*` unless Terraform
  provider behavior proves an additional describe action is required.
- Scope mutable ELBv2 permissions to the resource types the provisioner actually
  manages. For the current `gwlb` policy surface, that means Gateway Load
  Balancer ARNs, target group ARNs, and Gateway Load Balancer listener ARNs.
  Do not copy Application Load Balancer `app` listener-rule patterns into the
  GWLB statement unless the runtime creates those resources.
- Use existing module locals for region/account interpolation:
  `local.region` and `local.account_id`. Do not introduce duplicate
  caller-identity or region data sources.
- Derive resource-name patterns from the existing naming contract. The issue's
  suggested `shifter-*` pattern is not automatically authoritative here:
  portal module names use `var.name_prefix` values like `dev-portal`, while
  runtime NGFW Terraform uses `ngfw-user-{user_id}`. Confirm the managed ELBv2
  names before selecting an ARN pattern.
- Add tag conditions where ELBv2 supports them. Creation-time actions should
  require the Shifter ownership request tags; existing-resource mutations should
  require Shifter ownership resource tags.
- Preserve the existing Terraform style in this module: inline
  `jsonencode(...)` policies, `Sid` names that describe the action family, and
  short comments only where AWS requires a wildcard or dependent action.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #46 |
| --- | --- | --- |
| Engine-provisioner IAM ownership | `platform/terraform/modules/engine-provisioner/iam.tf` | Keep the ELBv2 repair in the existing `aws_iam_role_policy.gwlb` boundary unless the role split itself changes. |
| Region/account interpolation | `platform/terraform/modules/engine-provisioner/main.tf` `local.region` and `local.account_id` | Reuse these locals for ARN construction. |
| Runtime ownership tags | `shifter/engine/provisioner/components/tags.py`, `shifter/engine/provisioner/terraform/modules/ngfw/main.tf`, and `shifter/engine/provisioner/terraform/modules/range/main.tf` | IAM tag conditions should align to `shifter:system = shifter`, `shifter:environment = var.environment`, and `ManagedBy = terraform`. |
| Existing IAM hardening pattern | `scripts/check_tf_iam_ec2_scope/check_tf_iam_ec2_scope.py` | If regression coverage is added, follow the focused repo-native static-check style instead of adding a second policy framework. |
| Terraform security gate | `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, ADR-004-R11 | Narrowing ELBv2 wildcards should not be hidden by the broad Checkov skip; update the ADR exception text if it stops accurately describing accepted risk. |
| Local and CI Terraform gates | `.pre-commit-config.yaml`, `.github/workflows/_quality.yml`, `.tflint.hcl` | Keep local and CI validation aligned; do not add a check in only one place. |

## Cross-Cutting Layers

- IAM auth surface: the design touches the engine-provisioner ECS task role.
  Read/list actions may remain wildcard when AWS requires it. Mutable actions
  should be scoped to ELBv2 resource ARNs and Shifter ownership tags.
- AWS policy-resource shape: Gateway Load Balancer ARNs use `gwy`, not `app`.
  Relevant ELBv2 patterns are
  `loadbalancer/gwy/<name>/<id>`, `listener/gwy/<lb-name>/<lb-id>/<listener-id>`,
  and `targetgroup/<name>/<id>`. Listener rules are `app`/`net` resources and
  are not part of the GWLB surface unless a separate ALB/NLB use case is added.
- Tagging authorization: tagged creates need both the create action and
  `elasticloadbalancing:AddTags`. Creation-time `AddTags` should be constrained
  with `elasticloadbalancing:CreateAction`; later tag mutations should be
  resource-scoped and resource-tag-gated.
- Secret-handling surface: unchanged. This fix should not add secrets, secret
  values, secret references, KMS grants, tfvars values, or task-definition
  plaintext environment variables.
- Env-binding shape: unchanged unless the implementation proves that ELBv2 name
  patterns must be configured. If a pattern seam is needed, keep it as a typed
  Terraform module input or centralized local, not an ECS environment variable.
- OS/process exposure: Terraform may render ARNs in plans and IAM policy JSON;
  no credentials or secret values should be introduced on command lines, in
  process argv, or in generated env files.
- Error/log envelope: runtime error handling is out of scope. If a permission
  mistake later surfaces through provisioner AWS calls, preserve the existing
  `CommandResult`/logger pattern and do not leak credentials or full provider
  payloads in logs.
- Config and validation gates: Terraform changes must pass `terraform fmt`,
  `terraform validate`, TFLint, Checkov's canonical config, and ADR guard.
  Architecture guardrail changes must update ADR docs in the same change.

## Extensibility Boundary

The seam is the managed ELBv2 resource-name pattern and resource-type list.
Keep it centralized in one local value or one typed module input if the current
names cannot be expressed from existing variables. A future ALB/NLB variation
should require adding explicit `app` or `net` resource patterns, not broadening
the GWLB statement back to `Resource = "*"`.

## Gotchas And Anti-Patterns

- Do not hard-code `shifter-*` unless the managed ELBv2 resources actually use
  that prefix in every environment.
- Do not use Application Load Balancer ARN paths (`app`) for Gateway Load
  Balancer resources (`gwy`).
- Do not add unused ELBv2 actions from the issue suggestion, such as listener
  rule or security-group mutations, unless the provisioner currently performs
  those operations.
- Do not rely on `Resource` ARNs alone for ownership. Pair them with Shifter
  request/resource tag conditions where AWS supports the condition keys.
- Do not make Checkov skips broader, turn Checkov soft-fail on, or treat the
  existing ADR-004-R11 exception as permission to leave newly scopeable ELBv2
  writes on wildcard resources.
- Do not split IAM into a new module, policy generator, schema, or exception
  hierarchy for this narrow repair.
- Do not rename resource tags or runtime names in the same change. That turns a
  least-privilege repair into a runtime migration.

## Non-Goals

- No redesign of the engine provisioner, NGFW provisioning, VPC endpoint
  handling, runtime Terraform modules, cloud-provider adapters, or Django data
  model.
- No new Ground Control requirement, public API, DTO, validation schema,
  persistence path, logging framework, or secret-management behavior.
- No cleanup or recreation of existing load balancers, target groups, listeners,
  VPC endpoints, or route tables.
- No broad Terraform/Checkov policy overhaul beyond keeping documentation and
  local/CI enforcement consistent with the scoped IAM change.

## Validation Expectations

At minimum, the implementation should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd platform/terraform && tflint --recursive --config ../../.tflint.hcl
```

Also run `terraform fmt`/`terraform validate` for the touched Terraform root or
module. If a new IAM static checker is added, run its unit tests and wire the
checker through both pre-commit and CI.

## References

- AWS Service Authorization Reference:
  <https://docs.aws.amazon.com/service-authorization/latest/reference/list_awselasticloadbalancingv2.html>
- AWS ELB tagging during creation:
  <https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/tagging-resources-during-creation.html>
