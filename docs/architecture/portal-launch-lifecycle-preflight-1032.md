# Portal Launch Lifecycle Completion Preflight (#1032)

Status: pre-implementation guidance

Date: 2026-07-05

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1032>

This is a requirement-free preflight. GitHub issue #1032 is the shipping
contract. This note is intentionally not an implementation plan.

## Scope Boundary

Issue #1032 is about AWS portal instances that finish bootstrap but remain in
ASG `Pending:Wait` because the launch lifecycle hook is not completed. Keep
these concepts separate:

1. Cloud-init completion: the host finished running `user_data.sh`.
2. Container readiness: portal and worker containers are running and healthy.
3. Launch lifecycle completion: the ASG receives `CONTINUE` for the launching
   instance and can move it toward `InService`.
4. ALB readiness: the target group marks the instance healthy.
5. Termination drain: the separate #931 `EC2_INSTANCE_TERMINATING` hook.

Cloud-init `done`, Docker health, and ALB target health are not substitutes for
launch lifecycle completion. If a launch hook is configured, successful
bootstrap includes successful lifecycle completion.

## Architecture Decisions

- Keep lifecycle completion inside the existing AWS portal EC2 bootstrap path:
  `platform/terraform/modules/portal/ec2/user_data.sh`.
- Resolve the ASG name at completion time with bounded retry. Early discovery
  may remain a cache, but it must not be the only chance to find the ASG.
- Treat a configured launch hook with no resolved ASG name as a bootstrap
  failure, not a successful bootstrap. The success banner must be printed only
  after `complete-lifecycle-action CONTINUE` succeeds or no launch hook exists.
- Preserve the existing split between the launch hook and the #931 termination
  drain hook. Do not reuse the termination hook, its passive timeout semantics,
  or `default_result = "CONTINUE"` for launch bootstrap.
- Preserve Terraform as the ASG topology owner. Do not add GitHub variables,
  SSM parameters, or hardcoded names as a second source of ASG truth.
- Keep IAM least privilege: reuse the current `autoscaling:CompleteLifecycleAction`
  grant scoped to the portal ASG and the AWS-required wildcard
  `DescribeAutoScalingInstances` statement. Do not add broad Auto Scaling
  mutation permissions.
- Coverage should pin the failure mode: a launch-hook bootstrap path must not
  silently skip lifecycle completion and still print successful bootstrap.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1032 |
| --- | --- | --- |
| Fresh-boot bootstrap | `platform/terraform/modules/portal/ec2/user_data.sh` | Put ASG discovery retry and fail-loud lifecycle completion here. Do not add a separate bootstrap script. |
| Portal ASG and lifecycle hooks | `platform/terraform/modules/portal/ec2/main.tf`, `variables.tf`, `outputs.tf` | Reuse the existing launch hook name, ASG resource, IMDSv2 settings, and lifecycle IAM shape. |
| Termination drain precedent | `docs/architecture/aws-long-lived-connection-drain-preflight-931.md` and `aws_autoscaling_lifecycle_hook.terminate` | Keep launch completion distinct from passive termination drain. |
| Worker supervision ordering | `docs/architecture/worker-health-actionable-preflight-953.md`, `test_worker_health_supervision.py` | Keep worker-health installation before launch completion so a new instance is not admitted before supervision is active. |
| Deploy topology | `scripts/portal_deploy/portal_deploy.py` and `.github/workflows/_shifter-platform.yml` | Workflow ASG mode stays derived from Terraform outputs. Do not make workflow output discovery drive instance-side lifecycle completion. |
| Runtime config hydration | `platform/terraform/modules/portal/ssm`, `user_data.sh`, `scripts/portal-deploy/deploy_portal.sh` | Reuse existing SSM/env validation patterns if any new non-secret retry knob is introduced. Avoid new secret/config schemas for lifecycle identity. |
| Platform structural tests | `shifter/shifter_platform/tests/platform/*`, `scripts/portal_deploy/tests/test_portal_deploy.py` | Add focused tests near the existing platform invariants. Prefer behavior/structure checks over brittle shell line snapshots. |
| ADR and IaC enforcement | `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, `.github/workflows/_quality.yml` | Terraform or workflow edits must keep the existing checks fail-loud. Do not weaken architecture gates. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- IAM surface: instance-side lifecycle completion uses the portal EC2 instance
  role. It must keep `autoscaling:CompleteLifecycleAction` scoped to
  `aws_autoscaling_group.this[0].arn`, and `DescribeAutoScalingInstances` may
  remain `Resource="*"` because AWS Describe APIs require it. Do not introduce
  `autoscaling:*`, wildcard mutation, or deploy-role dependencies.
- IMDS surface: `user_data.sh` already runs with IMDSv2 required,
  `instance_metadata_tags = "enabled"`, and hop limit 2. Any fallback that uses
  IMDS must use the existing IMDSv2 posture, bounded curl timeouts, and no IMDSv1
  fallback. The IMDS token is not an AWS credential, but it must not be logged,
  exported, or exposed through `set -x`.
- Secret-handling surface: lifecycle hook name, ASG name, instance id, region,
  retry count, and completion result are non-secret operational identifiers.
  Logs must not include SSM parameter values, secret ARNs beyond existing
  references, Docker env, `docker inspect` output, IMDS token values, Redis
  AUTH material, DB settings, Guacamole tokens, SSH keys, or rendered env dumps.
- Env/config shape: existing Terraform template values are the binding surface
  for `AWS_REGION`, `LIFECYCLE_HOOK_NAME`, and non-secret bootstrap constants.
  If retry counts or delays become configurable, make them Terraform variables
  with numeric validation and feed them through the `templatefile` contract; do
  not create a workflow-only or SSM-only ASG identity source.
- OS/process exposure: AWS CLI argv may contain ASG name, hook name, instance
  id, region, and result only. These are acceptable. Do not pass secrets or
  full environment payloads in shell command strings, process argv, or cloud-init
  output.
- Bootstrap error envelope: there is no user-facing HTTP envelope in scope.
  Failures surface through cloud-init output, ASG lifecycle state, and instance
  replacement. A failed required lifecycle completion must exit non-zero and
  must not print `Shifter Platform bootstrap complete!`.
- Observability surface: cloud-init output should include the completion attempt
  and result. Existing ALB health and ASG image verification remain post-deploy
  evidence, but they do not prove launch lifecycle completion by themselves.

Maintainability incumbents the implementation must build on:

- `user_data.sh` for instance-side launch lifecycle logic.
- `portal/ec2/main.tf` for lifecycle hooks, IAM, launch template, IMDSv2, and
  worker-health artifact injection.
- `portal_deploy.py` and `_shifter-platform.yml` for workflow topology and ASG
  deploy verification, not for bootstrap-time ASG identity.
- Existing platform tests for structural deployment invariants.
- Prior preflight notes for #931 and #953 to preserve hook separation and
  supervisor-before-admission ordering.

Extensibility seam:

The seam belongs in a small lifecycle helper inside `user_data.sh`:

- `resolve_asg_name`: bounded retry, preferably using
  `describe-auto-scaling-instances`, with any fallback sharing the same
  retry/fail-loud contract.
- `complete_lifecycle_action RESULT`: resolves or refreshes ASG identity at the
  point of completion and treats required completion failure as fatal.
- Optional non-secret parameters: discovery attempts, discovery delay seconds,
  and AWS CLI timeout values. If they need environment variation, define them at
  the Terraform module boundary with validation.

The next likely variation is warm-pool reuse, longer first-boot latency, or an
additional launch-health prerequisite. Those should change parameters or extend
the helper, not create another ASG lifecycle implementation.

## Whole-Repo Scope

Likely in scope for implementation:

- `platform/terraform/modules/portal/ec2/user_data.sh`
- `platform/terraform/modules/portal/ec2/main.tf`
- `platform/terraform/modules/portal/ec2/variables.tf` if retry knobs become
  module inputs
- `shifter/shifter_platform/tests/platform/` for a launch lifecycle structural
  test
- `.github/workflows/_shifter-platform.yml` only if a post-refresh smoke check
  is added to verify no instances remain `Pending:Wait`

Usually out of scope:

- `scripts/portal-deploy/deploy_portal.sh`, unless a shared helper is factored
  in a way that also affects redeploy behavior. Redeploy does not complete ASG
  launch lifecycle actions.
- Portal Django settings, schemas, DTOs, controllers, services, repositories,
  migrations, and exception hierarchy.
- GCP/Kubernetes deployment paths.
- Guacamole, CTF scoring, range provisioning, SQS worker contracts, Redis
  channel-layer selection, and RDS connection behavior.

## Gotchas And Anti-Patterns

- Do not print `Shifter Platform bootstrap complete!` after skipping lifecycle
  completion for a configured launch hook.
- Do not swallow `complete-lifecycle-action` failure with a warning and return
  success on the required launch path.
- Do not cache an empty ASG name from early boot and treat it as authoritative
  after the rest of bootstrap succeeds.
- Do not conflate the launch hook with the termination-drain hook. Launch
  defaults to fail closed; termination drain is passive timeout with
  `default_result = "CONTINUE"`.
- Do not broaden IAM to work around discovery failure.
- Do not add ASG name to SSM Parameter Store or GitHub Actions variables as a
  second topology source.
- Do not weaken IMDSv2, expose SSH, broaden security groups, or change ALB
  health checks to compensate for lifecycle completion.
- Do not log full AWS CLI responses, Docker env, SSM parameters, secrets, or
  IMDS tokens while adding debug output.
- Do not make the portal container or Django app responsible for ASG lifecycle
  completion. This is host bootstrap infrastructure, not application runtime.

## Non-Goals

- No implementation in this preflight note.
- No redesign of portal autoscaling, target tracking, ALB readiness,
  termination drain, worker-health remediation, deploy topology, or image
  verification.
- No new Terraform module, Python package, metrics framework, app schema,
  database table, DTO, serializer, controller, service, repository, or
  exception type.
- No Ground Control traceability work; this run is requirement-free and issue
  driven.

## Validation

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups that touch Terraform or workflow surfaces must also
run the stack-native checks for those surfaces, especially:

```bash
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
cd shifter/shifter_platform && uv run pytest tests/platform
```
