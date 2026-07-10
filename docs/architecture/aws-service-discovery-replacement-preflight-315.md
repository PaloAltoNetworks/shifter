# AWS Service Discovery Replacement Preflight (#315)

Status: pre-implementation guidance

Date: 2026-06-29

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/315>

## Scope Boundary

This issue is requirement-free. GitHub issue #315 is the shipping contract:
AWS platform CI/CD must handle Terraform replacement of Guacamole Service
Discovery services without manual intervention, with enough diagnostics to
debug failed replacement handling.

Do not implement the fix in this note. The implementation should make the
smallest deploy-workflow and documentation change needed to handle replacement
of `aws_service_discovery_service` resources that still have ECS-registered
instances.

## Architecture Decisions

- Treat Service Discovery replacement handling as deploy orchestration, not as
  application behavior. It belongs on the AWS platform Terraform apply path,
  immediately after creating the local saved `tfplan` and before applying that
  same file.
- Keep the saved-plan contract from ADR-003-R2: the replacement detector and
  `terraform apply` must consume the same local `tfplan`. Do not re-plan after
  scaling ECS services down.
- Detect replacement from Terraform plan JSON by resource type and actions, not
  string-matched plan text. Replacement appears as a delete-bearing action on
  `aws_service_discovery_service`; the issue's observed trigger is
  `health_check_custom_config.failure_threshold`, but the detector must not be
  hard-coded to that attribute only.
- Derive ECS cluster and service identity from Terraform outputs where possible.
  The portal roots already expose `guacamole_ecs_cluster_name`,
  `guacd_service_name`, and `guacamole_client_service_name`; do not duplicate
  the naming formula in workflow shell as the primary contract.
- Move non-trivial replacement handling out of ad hoc workflow shell if the fix
  grows beyond a few lines. The repo already has unit-testable deploy helpers
  with injected command runners; prefer that shape over another inline parser.
- Scaling an ECS service to zero is an out-of-band mutation. The implementation
  must snapshot desired counts and restore intended counts after apply, or in a
  safe failure path, instead of relying on Terraform drift correction. This is
  especially important because `aws_ecs_service.guacd` ignores desired-count
  drift.
- If the plan deletes both Service Discovery services, drain both registered
  ECS services. The current Guacamole module registers both `guacd` and
  `guacamole-client`; scaling only one tier is not a general replacement fix.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #315 |
| --- | --- | --- |
| Saved-plan apply | `.github/workflows/_shifter-platform.yml`, ADR-003-R2 in `docs/adr/index.yaml`, `scripts/adr_guard/adr_guard.py` | Keep `terraform plan ... -out=tfplan`, inspect that plan, then `terraform apply -lock-timeout=5m tfplan`. |
| Guacamole topology | `platform/terraform/modules/guacamole/main.tf`, `ecs.tf`, `outputs.tf` | Reuse the existing Cloud Map namespace/services, ECS service registries, desired-count ownership, and exposed cluster/service outputs. |
| Portal roots | `platform/terraform/environments/{dev,proof,prod}/portal/outputs.tf` | Use the root outputs as the service-name contract instead of hard-coded `${ENV}-portal-*` assumptions. |
| Deploy helper style | `scripts/check_rds_pending_modifications/check_rds_pending_modifications.py`, `scripts/assert_portal_inspection/assert_portal_inspection.py`, `scripts/portal_deploy/portal_deploy.py` | Use AWS CLI subprocesses, no boto3 dependency, bounded polling, injected runners for tests, sanitized diagnostics, and non-zero exits on failed verification. |
| Post-deploy verification | `scripts/portal_deploy/portal_deploy.py verify-post-deploy` and `.github/workflows/_shifter-platform.yml` verify jobs | Do not duplicate Guacamole stabilization semantics; replacement handling should feed into the existing fail-loud verification path. |
| Deploy auth | `aws-actions/configure-aws-credentials`, GitHub OIDC deploy role, `platform/terraform/global/iam/github-oidc.tf` | Keep AWS API access on the existing OIDC surface. Any new AWS actions must fit the deploy role's least-privilege policy and IAM size checks. |
| IaC guardrails | `.gc/plan-rules.md`, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml`, `actionlint` | Workflow/Terraform changes must preserve ADR guard, TFLint, Checkov, and actionlint coverage. |

## Cross-Cutting Layers

- GitHub/OIDC auth surface: the workflow must continue using
  `aws-actions/configure-aws-credentials` with `id-token: write`. Do not add
  long-lived AWS keys, PATs, extra environments, or pull-request deploy access.
- Secret-handling surface: plan inspection, ECS service names, Cloud Map
  service IDs, ARNs, desired counts, task counts, and instance counts are
  deploy diagnostics. Do not print rendered `local.auto.tfvars`, AWS
  credentials, Secrets Manager values, SSM secure parameters, Guacamole tokens,
  signed URLs, RDP passwords, SSH keys, or full task definitions.
- Env-binding shape: target environment still comes from
  `inputs.environment`; deployment values still come from
  `TF_VARS_<ENV>_PORTAL` rendered into gitignored `local.auto.tfvars`. Do not
  add a parallel env var parser or a second per-environment naming schema.
- Terraform/provider validators: keep Terraform fmt/validate, saved-plan apply,
  state-lock timeout, TFLint, Checkov, and ADR guard intact. The replacement
  handler is an additional deploy orchestration step, not a substitute for
  provider planning.
- AWS live-state validators: before deleting a Service Discovery service,
  verify the affected ECS service exists, capture desired/running counts, scale
  to zero, wait for running tasks to drain, and confirm the Cloud Map service
  has no registered instances or that ECS has fully deregistered them. Bounded
  waits must fail loud on timeout.
- OS/process exposure: use argv-safe subprocess calls or strict shell. Do not
  put secrets in command arguments, do not enable shell tracing around secret
  rendering, and do not write sensitive Terraform output to side files.
- Error envelope and observability: failures should produce GitHub Actions
  `::error::` diagnostics naming the environment, Terraform address, ECS
  cluster, ECS service, desired/running counts, Cloud Map service id/name,
  wait attempt, and AWS status. Keep messages actionable and bounded.

## Extensibility Seam

The seam is a small mapping from Terraform plan resource address to the ECS
service that owns the registrations. For the current Guacamole module:

- `module.guacamole.aws_service_discovery_service.guacd` maps to
  `guacd_service_name`.
- `module.guacamole.aws_service_discovery_service.guacamole_client` maps to
  `guacamole_client_service_name`.

Keep that mapping centralized in the helper or workflow step that interprets
the plan. A future Service Discovery consumer should add one mapping entry and
one output, not clone the whole drain/deregister/apply workflow.

## ForceNew Documentation Guardrail

The implementation must document Service Discovery attributes that force
replacement for the active AWS provider version. At minimum, this issue's
observed replacement path is:

- `aws_service_discovery_service.health_check_custom_config.failure_threshold`

Do not present this as exhaustive unless the list is verified against the
provider schema or official provider documentation for the version in use.
Prefer documenting the provider-version caveat and the operational rule:
delete-bearing changes to `aws_service_discovery_service` require ECS
deregistration before apply.

## Gotchas And Anti-Patterns

- Do not scale `guacd` to zero and assume Terraform will restore it.
  `aws_ecs_service.guacd` has `lifecycle.ignore_changes = [desired_count]`.
- Do not scale only `guacd` when the plan deletes the `guacamole-client`
  Service Discovery service too. Both ECS services have `service_registries`.
- Do not hard-code service names as the only source of truth when Terraform
  already exposes outputs for the cluster and services.
- Do not inspect human-readable plan text with fragile grep patterns. Use
  `terraform show -json tfplan` and fail on malformed or missing plan JSON.
- Do not treat `terraform plan` exit code `2` as failure when
  `-detailed-exitcode` is used; do treat every other non-zero exit as fatal.
- Do not turn replacement-handling timeouts into warnings. A green run that
  leaves registered instances behind or services scaled down is a failed deploy.
- Do not use `terraform state rm`, manual import, or ignore_changes as the
  first-line CI/CD fix. Those are operator recovery tools or drift suppressors,
  not reliable automated replacement orchestration.
- Do not broaden IAM, security groups, WAF, ALB routing, or Guacamole auth to
  work around Service Discovery replacement.
- Do not add a duplicate workflow language, schema, exception hierarchy,
  logging framework, or AWS SDK dependency for this narrow deploy concern.

## Non-Goals

- No implementation in this preflight note.
- No Terraform state surgery, import workflow, force-push/rebase workflow, or
  manual cleanup runbook as the primary automated fix.
- No change to Guacamole JSON auth, token lifecycle, Mission Control views,
  Django DTOs/controllers/services/repositories, database schemas, or runtime
  error envelopes.
- No redesign of Cloud Map, ECS service discovery, ALB routing, VPC topology,
  security groups, IAM trust policy, or Guacamole scaling posture unless plan
  evidence proves the current topology cannot support automated replacement.
- No weakening of ADR guard, TFLint, Checkov, actionlint, gitleaks, deploy
  runner gating, saved-plan apply, or post-deploy verification.

## Validation Expectations

For the implementation that follows, run the checks for every touched surface.
For workflow and Terraform changes this should include at least:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
```

If a helper script or `portal_deploy.py` subcommand is added, include focused
unit tests for plan detection, ECS drain timeout, desired-count restoration, and
sanitized diagnostics.
