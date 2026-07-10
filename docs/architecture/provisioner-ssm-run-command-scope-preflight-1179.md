# Provisioner SSM Run Command Scope Preflight (#1179)

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1179>

Source context: Codex Security finding `csf_f6bdcef088d391e2285d33e3`
flags the engine-provisioner ECS task role because `ssm:SendCommand` can target
any EC2 instance ARN in the account. The cited runtime sink is the generic
`SSMExecutor`; the cited control is the task-role policy attached through the
engine-provisioner ECS task definition.

This note is not an implementation plan. It records the repo-wide boundaries,
canonical incumbents, and anti-patterns the implementation must preserve.

## Scope Boundary

Issue #1179 is an AWS control-plane IAM hardening change. The implementation
should narrow the engine-provisioner task role from account-wide SSM Run
Command to Shifter range guest instances only.

In scope:

- `platform/terraform/modules/engine-provisioner/iam.tf`
- the engine-provisioner module input/local shape only if needed to express
  reusable target-tag and document contracts
- Terraform/IAM regression tests or a repo-native checker proving portal and
  GitHub runner instances are denied
- ADR exception metadata only if a waiver changes or a new guardrail checker is
  wired into pre-commit/CI

Out of scope unless the implementation proves it is unavoidable:

- changing `SSMExecutor` authorization behavior
- changing setup plans, orchestration retries, password push semantics, or
  command templates
- changing portal deployment SSM workflows or GitHub OIDC deployment roles
- introducing per-range ECS task roles or STS session-tagging

## Architecture Decisions

- Treat IAM as the authorization boundary. `SSMExecutor` is intentionally a
  transport adapter with no range-ownership knowledge; keep it generic and let
  AWS IAM deny unsafe targets.
- Split SSM command execution by resource family. Instance authorization must
  carry SSM-supported instance resource-tag conditions; SSM document
  authorization must stay pinned to the exact AWS managed documents already in
  use (`AWS-RunShellScript`, `AWS-RunPowerShellScript`). Do not put document
  ARNs and tagged instance ARNs in one condition block that accidentally makes
  either side unguarded or uncallable.
- Result polling is a different permission from command execution. Keep
  `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations`, and
  `ssm:DescribeInstanceInformation` out of the `ssm:SendCommand` statement.
  If AWS still requires wildcard resources for polling/describe, leave those
  read-only statements separate and enumerated.
- Reboot is not SSM command execution. Scope `ec2:RebootInstances` with the
  existing EC2 resource-tag pattern instead of bundling it into the SSM
  statement.
- Bind to the existing range tag contract. Range EC2 instances from
  `shifter/engine/provisioner/terraform/modules/range/main.tf` already carry
  `shifter:system=shifter`, `shifter:environment`, `shifter:range_id`,
  `shifter:request_uuid`, `shifter:instance_uuid`, `ManagedBy=terraform`,
  `shifter:role`, and `shifter:os`. Use those tags; do not invent a second
  ownership taxonomy.
- Generic tags are insufficient. Portal and range roots both use generic tags
  such as `Project`, `Environment`, and `ManagedBy`; the SSM condition must
  require range-specific Shifter tags such as `shifter:range_id`,
  `shifter:request_uuid`, and `shifter:instance_uuid` to deny portal and runner
  instances.
- Do not paper over this with a new ADR-004-R11 waiver. The existing
  engine-provisioner IAM exception explicitly relies on tag-scoped conditions
  where APIs support them. This finding is a candidate for narrowing, not an
  accepted-risk expansion.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1179 |
| --- | --- | --- |
| Engine task identity | `platform/terraform/modules/engine-provisioner/task_definition.tf` and `iam.tf` | Keep the ECS task role as the runtime identity; do not move authorization into Python. |
| Range EC2 tag contract | `shifter/engine/provisioner/terraform/modules/range/main.tf` and `components/tags.py` | Reuse existing Shifter range tags; do not add a new owner tag unless the range tag contract itself is intentionally changed. |
| EC2 IAM tag scoping | `platform/terraform/modules/engine-provisioner/iam.tf` `ec2_provisioning` and `ec2_run_instances` | Mirror the established request-tag/resource-tag condition style for mutable EC2 actions. |
| Static IAM guardrails | `scripts/check_tf_iam_ec2_scope/` and `scripts/check_tf_iam_elb_scope/` | If a new checker is needed, make it `check_tf_iam_ssm_scope` in the same style, with unit tests and pre-commit/CI wiring. |
| Terraform runner secret hygiene | `shifter/engine/provisioner/terraform_base.py` | Keep Terraform inputs in staged `terraform.tfvars.json`; do not pass policy material or secrets through ad hoc shell/env paths. |
| SSM command transport | `executors/ssm_executor.py`, `executors/base.py`, `SetupOrchestrator` | Preserve `CommandResult`, shared executor exceptions, retry behavior, truncation, and sensitive-output masking. |
| Guest credential handling | `plans/set_local_password.py`, `instance_setup.py`, range module SSM SecureString outputs | Do not undo the #762 mitigation: passwords stay out of user data and process argv, and AWS uses `{{ssm-secure:...}}` substitution. |
| ADR/check lifecycle | ADR-004-R11, `docs/adr/exceptions.yaml`, `docs/adr/README.md`, `.pre-commit-config.yaml`, `_quality.yml` | Guardrail-file changes need matching ADR docs; accepted-risk metadata must describe the actual remaining risk. |

## Cross-Cutting Layers The Design Must Pass

- AWS IAM authorization: `ssm:SendCommand` must allow only tagged range EC2
  instance resources and only the existing shell/PowerShell SSM documents.
  Use IAM condition keys that AWS Systems Manager evaluates for EC2 instance
  targets, and prove the policy denies portal and GitHub runner instance tag
  shapes.
- Terraform shape: keep policy JSON generated through `jsonencode` in the
  engine-provisioner module. If required tag keys or allowed document names are
  repeated, centralize them in module locals so the policy and tests do not
  drift.
- Range tag validation: the target condition depends on the range module's
  required tags. If the implementation changes that contract, update
  `components/tags.py` tests and the range Terraform module together.
- Auth surface: the only in-scope principal is the engine-provisioner ECS task
  role. Do not modify Django auth, portal session auth, GitHub Actions OIDC,
  or SSM managed-instance agent roles to solve this issue.
- Secret-handling surface: the change should not introduce new secret values.
  Existing per-instance passwords remain in Secrets Manager plus SSM
  SecureString references; command bodies must keep using the established
  `{{ssm-secure:...}}` path.
- Env-binding surface: task environment variables in `task_definition.tf` and
  runtime parsers in `terraform_vars.py` should stay unchanged unless a new
  module input is genuinely required. Do not add target-instance IDs, tag
  values, or policy fragments as environment variables.
- OS/process exposure: Terraform continues to run through `subprocess.run`
  list argv with no shell. Guest password setup continues to avoid process argv
  (`chpasswd` stdin or PowerShell `SecureString`). Do not put SSM command JSON,
  passwords, or AWS tokens in workflow logs, process arguments, user data, or
  generated env files.
- Error envelope/logging: preserve `SSMExecutor` and `SetupOrchestrator`
  exception/logging contracts. Access-denied failures should remain operational
  errors; do not expose IAM policy details, target tags, command bodies, or
  secret placeholders through user-facing portal errors.
- Repo enforcement: changes under `platform/terraform/modules/engine-provisioner`
  must pass ADR guard, Checkov, TFLint, Terraform validation, and any new
  `check_tf_iam_*` regression checker.

## Extensibility Seam

The immediate seam is the target-identity predicate: a single module-local
definition of the required range instance tags and allowed SSM documents.

The next likely variation is stronger per-range containment. Tag-only scoping
to `shifter:system`, environment, and range-instance existence contains the
task role to Shifter range guests, but it does not prove a compromised
environment-wide provisioner task can only command one user's range. If future
work requires per-range isolation, use an explicit per-range authorization
mechanism such as per-range task roles or STS session tags bound to
`shifter:range_id`/`shifter:request_uuid`. Do not fake that boundary with a
Python pre-check before `send_command`; a compromised task can bypass local
checks if IAM still permits the call.

## Gotchas And Anti-Patterns

- Do not scope only to `ManagedBy=terraform` or generic `Environment=dev`; that
  can still include portal infrastructure and other non-range resources.
- Do not use EC2 condition keys where SSM expects SSM resource-tag condition
  keys for `ssm:SendCommand` instance targets. Confirm the exact key family
  against IAM simulation, then codify it in tests.
- Do not let a document-ARN allow statement accidentally authorize
  `ssm:SendCommand` to all instances. Documents and instances need separate
  effective authorization.
- Do not broaden allowed SSM documents beyond the two existing AWS managed
  documents as a convenience.
- Do not collapse read/poll permissions into a wildcard action such as
  `ssm:*Command*`.
- Do not change `SSMExecutor` to look up EC2 tags or query the database for
  ownership. That duplicates IAM policy, couples transport to domain state, and
  is bypassable under the stated threat model.
- Do not confuse SSM managed-instance agent permissions
  (`AmazonSSMManagedInstanceCore` or the runner inline equivalent) with the
  control-plane permission to run commands from the provisioner role.
- Do not weaken ADR-004-R11, Checkov, TFLint, or local IAM checker routing to
  make the patch land.

## Non-Goals

- No rewrite of setup plans, `SetupOrchestrator`, `SSMExecutor`, executor
  exceptions, or `CommandResult`.
- No change to portal deployment via SSM, migration commands, or post-deploy
  smoke workflows.
- No redesign of per-instance password generation, SSM SecureString
  substitution, Secrets Manager lookups, or Terraform state handling.
- No GCP/GDC executor changes.
- No per-user or per-range runtime role model in this issue unless the
  implementation is explicitly expanded beyond the public acceptance criteria.
- No PR merge, deployment, or production apply sequencing guidance in this
  preflight.

## Validation Expectations

For the implementation that follows, add evidence that the engine-provisioner
task role cannot send commands to non-range instances:

- policy simulation or deterministic rendered-policy tests denying portal EC2
  tag shapes
- policy simulation or deterministic rendered-policy tests denying GitHub
  runner EC2 tag shapes
- positive coverage for a tagged range guest instance using the existing
  shell/PowerShell documents
- a static guardrail in the existing `scripts/check_tf_iam_*` style if the
  policy shape is important enough to protect beyond unit tests

Run the repo-required Terraform and architecture checks for touched surfaces,
including:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

If a new checker or workflow hook is added, update `docs/adr/README.md`,
`.pre-commit-config.yaml`, and `.github/workflows/_quality.yml` together and
run that checker plus its unittest suite.
