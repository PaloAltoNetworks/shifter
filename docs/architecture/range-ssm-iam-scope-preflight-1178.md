# Range SSM IAM Scope Preflight

Status: pre-implementation guidance

Date: 2026-06-27

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1178>

This note records the architecture boundary for fixing the range instance role
that can read and mutate every range's SSM Parameter Store namespace. It is not
an implementation plan.

## Decision Boundary

Range SSM parameters are runtime range data. A range guest principal must be
able to access only the SSM parameters for its own deployment environment and
range ID.

The durable contract is:

- The AWS-enforced principal-to-parameter binding must include both
  `environment` and `range_id`.
- The parameter namespace remains
  `/shifter/${environment}/range/${range_id}/...`; do not introduce a second
  range credential path or encode the boundary in app-only state.
- The DC write path and member read path are separate privileges. Non-DC range
  members should not receive `ssm:PutParameter` or `ssm:DeleteParameter`.
- KMS access for SSM SecureString values must stay service-scoped to SSM and
  should be narrowed to the relevant CMK or SSM encryption context where the
  Terraform surface can express that safely.
- The existing shared range instance role is not a valid per-range boundary by
  itself. If the final design cannot bind IAM conditions to the current range
  identity for that shared role, use per-range instance roles/profiles or an
  equivalent AWS-enforced principal split.

Environment-only scoping, such as `parameter/shifter/${environment}/range/*`,
does not satisfy the issue because every range in the same environment would
still be in blast radius.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Stable range instance role | `platform/terraform/modules/range/vpc/iam.tf` | This owns the current shared instance profile and the vulnerable SSM policy. Do not add a second stable wildcard policy elsewhere. |
| Runtime range parameters | `shifter/engine/provisioner/terraform/modules/range/main.tf` | Keep SSM parameter names range-scoped by `var.environment` and `var.range_id`; both `guest_password` and `dc_config` are in the same range namespace. |
| Runtime range state | `shifter/engine/provisioner/terraform/modules/range/outputs.tf`, `state_helpers.py` | Reuse `rdp_password_ssm_param_name` and `rdp_password_secret_arn`; do not add duplicate state fields for the same credential. |
| AWS password push | `instance_setup._set_local_password_or_raise` and `plans/set_local_password.py` | Keep using `{{ssm-secure:<name>}}` for AWS SSM Run Command so plaintext does not land in command history. |
| Terraform variable binding | `terraform_vars._build_range_terraform_variables`, `RangeConfig.environment`, `RANGE_INSTANCE_PROFILE_NAME` | Derive any new IAM/profile input from the existing range Terraform variable builder and environment contract. |
| Provisioner IAM | `platform/terraform/modules/engine-provisioner/iam.tf` | If runtime Terraform creates or passes new per-range roles, constrain create/pass/delete permissions with Shifter tags, environment, permissions boundary, and service-specific `iam:PassedToService`. |
| IAM naming | `scripts/check_tf_iam_role_naming`, `docs/architecture/iam-role-naming-preflight-253.md` | New roles/profiles must use the repo IAM naming seam and permissions-boundary convention. |
| IAM static checks | `scripts/check_tf_iam_ec2_scope`, `scripts/check_tf_iam_elb_scope`, `scripts/check_tf_kms_secrets_grant` | Regression coverage should follow the focused repo-native Python checker pattern and be wired into pre-commit and `_quality.yml`. |
| Secret boundary | `docs/architecture/vm-guest-credential-preflight-762.md`, `docs/architecture/secrets-manager-cmk-preflight.md` | Preserve the existing separation between Secrets Manager references, SSM SecureString push references, and plaintext values. |

## Cross-Cutting Layers

Security layers the implementation must satisfy:

- IAM auth surface: the range guest principal must be scoped to its own
  `environment` and `range_id`. A shared role with a range wildcard is not
  enough. If new per-range roles are created by runtime Terraform, provisioner
  IAM must be narrowly allowed to create, tag, pass, and destroy only
  Shifter-owned roles/profiles for EC2.
- SSM namespace surface: allowed resources must be concrete paths under
  `arn:aws:ssm:<region>:<account>:parameter/shifter/<environment>/range/<range_id>/*`.
  Do not grant `ssm:GetParametersByPath` or wildcard resources that cross the
  range segment.
- SSM action surface: split read and write actions by consumer. Member
  instances should need only read/decrypt for their own range parameters; DC
  instances may need write/delete for `dc-config` if that behavior remains.
- KMS gate: SecureString permissions must keep `kms:ViaService =
  ssm.<region>.amazonaws.com`. Prefer the concrete key ARN when available; if
  `Resource = "*"` remains necessary, add the narrowest supported SSM
  encryption-context condition rather than relying on ViaService alone.
- Secret-handling surface: secret values remain in Secrets Manager, SSM
  SecureString, or transient remote command substitution. Terraform variables,
  outputs, state payloads, user data, logs, and Python exception messages carry
  parameter names or secret ARNs, not plaintext.
- OS/runtime exposure: keep passwords out of EC2 user data, Docker arguments,
  process argv, shell tracing, and SSM command output. The existing
  `{{ssm-secure:<name>}}` path is the AWS incumbent for avoiding SSM command
  history leakage.
- Config and shape validators: Terraform changes must pass `terraform fmt`,
  TFLint, Checkov, and ADR guard. If IAM guardrails or workflows change, update
  the ADR docs/registry and run `actionlint` for workflow edits.
- Error and observability envelope: logs may name range ID, instance ID,
  parameter path, and IAM role/profile name. They must not print parameter
  values, resolved SecureString values, rendered command bodies containing
  plaintext, or full provider credential payloads.

Maintainability incumbents the implementation must build on:

- The range VPC Terraform module for stable shared infrastructure.
- The runtime range Terraform module for per-range AWS resources and outputs.
- The provisioner's existing Terraform variable builder and state helpers.
- The existing SSM executor/setup-plan error handling and output truncation.
- Repo-native Python IAM checkers, pre-commit hooks, `_quality.yml`, and
  `.github/quality-path-filters.yaml` for regression coverage.

Extensibility seam:

Keep the IAM scope seam parameterized by `environment`, `range_id`, and
consumer purpose (`dc-write` versus `member-read`). That lets the next
reasonable variation, such as per-instance SSM parameters, DC-only writes, or a
separate password-rotation actor, become a policy/action-set change rather than
a new SSM namespace, state schema, or secret abstraction.

## Whole-Repo Scope

In scope for the future implementation:

- AWS stable range infrastructure:
  `platform/terraform/modules/range/vpc/{iam.tf,variables.tf,outputs.tf}`.
- AWS runtime range Terraform:
  `shifter/engine/provisioner/terraform/modules/range/**`.
- Provisioner range variable/state flow:
  `terraform_vars.py`, `terraform_ops.py`, `state_helpers.py`, and
  `instance_setup.py`.
- Provisioner setup execution:
  `executors/ssm_executor.py`, `plans/set_local_password.py`,
  `plans/dc_setup.py`, and `plans/domain_join.py` when their SSM or password
  handling changes.
- Provisioner/platform IAM:
  `platform/terraform/modules/engine-provisioner/iam.tf` and any environment
  root that passes range role/profile outputs into the provisioner.
- Architecture enforcement:
  `.pre-commit-config.yaml`, `.github/workflows/_quality.yml`,
  `.github/quality-path-filters.yaml`, `scripts/check_tf_*`, `docs/adr/**`,
  and `docs/adr/exceptions.yaml` if a new guardrail or exception is introduced.

## Gotchas And Anti-Patterns

- Do not treat `parameter/shifter/${environment}/range/*` as fixed. It still
  permits cross-range access inside the environment.
- Do not rely on SSM parameter tags alone unless the principal is also
  range-bound in IAM. Shared principal tags on the existing role do not separate
  one range from another.
- Do not leave `ssm:PutParameter` or `ssm:DeleteParameter` on member instances
  for convenience.
- Do not add direct plaintext password fetches to user data, setup scripts,
  Terraform outputs, Django state, or SSM command logging.
- Do not conflate `/shifter/ami/*` config parameters with
  `/shifter/<environment>/range/<range_id>/*` credential parameters. AMI
  resolution remains the provisioner config-store concern.
- Do not add a new cloud secret abstraction, DTO, exception hierarchy, or state
  schema for this IAM-scoping fix.
- If runtime Terraform creates IAM roles/profiles, do not forget IAM eventual
  consistency, permissions boundaries, role cleanup on range destroy, and
  narrowly scoped `iam:PassRole`.
- Do not weaken Checkov, TFLint, ADR guard, pre-commit, or workflow routing to
  land the Terraform change.

## Non-Goals

- This preflight does not implement the IAM policy, Terraform role split, or
  regression checker.
- No migration or rotation of already-provisioned ranges is performed here.
- No redesign of CTF participant access, Mission Control access brokering,
  Guacamole, range placement, NGFW routing, or provider-neutral GCP runtime.
- No new Terraform test framework unless the implementation deliberately adopts
  it for the whole IAM-checker family.
- No broad cleanup of unrelated SSM parameters, AMI promotion workflows,
  workshop/demo ranges, or portal runtime secret hydration.

## Validation Expectations

At minimum, changes on this path should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Add targeted validation for touched surfaces:

- `terraform fmt` and `terraform validate` for modified Terraform modules and
  environment roots.
- A focused IAM regression check, following `scripts/check_tf_*`, that rejects
  `parameter/shifter/*/range/*`,
  `parameter/shifter/<environment>/range/*`, and write/delete actions on member
  policies.
- Unit tests for any new checker plus the existing `check_tf_*` checker suite.
- `actionlint` if workflows change.
- Provisioner tests around `rdp_password_ssm_param_name`,
  `{{ssm-secure:<name>}}`, and fail-closed missing parameter references if the
  password push path changes.
