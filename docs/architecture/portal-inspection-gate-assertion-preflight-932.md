# Portal Inspection Gate And Assertion Preflight (#932)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/932>

## Scope Boundary

This is a requirement-free architecture preflight. GitHub issue #932 is the
shipping contract: keep the AWS portal inspection path gated off until the
deploy has a post-apply assertion that proves the live Network Firewall
endpoints and route tables match per AZ, then fail the deploy when that proof
does not hold.

Do not implement the issue in this note. The implementation should make the
minimum infrastructure and deploy-verification change needed to prove the
existing `platform/terraform/modules/portal/vpc/inspection.tf` topology before
operators enable it.

## Architecture Decisions

- Keep `enable_portal_inspection` default-off in committed env baselines and
  deployment-secret examples until the assertion is part of the apply path.
  The current committed dev/prod portal tfvars enable it; #932 should treat
  that as drift from the new safety gate, not as precedent.
- Treat the post-apply assertion as deploy verification, not application
  runtime behavior. It belongs immediately after the portal Terraform apply in
  `.github/workflows/_shifter-platform.yml`, implemented either as a small
  script or as a narrowly scoped subcommand of an existing deploy helper.
- The assertion should compare three live surfaces from the same apply:
  Terraform outputs/state for expected VPC/subnet/route-table intent, AWS
  Network Firewall `firewall_status.sync_states` for endpoint identity and
  health, and EC2 route tables for the actual `vpc_endpoint_id` targets. A
  mismatch, missing endpoint, unhealthy sync state, or stale route is a failed
  deploy.
- Use the AWS CLI as the deploy-job interface, matching existing post-apply
  verifiers. Do not introduce boto3 or another AWS SDK unless an incumbent
  script already requires it.
- Keep the firewall policy visibility-first for this issue: stateful default
  pass with ALERT-only portal anomaly rules. The gate proves the inline path is
  wired and healthy; it does not convert alert-only inspection into traffic
  enforcement. A drop posture is a later architecture change because the
  current per-AZ endpoint model has known asymmetric cross-AZ stateful flows.
- The deliberate-broken-endpoint acceptance test should be a testable negative
  path for the assertion, not a production break-glass procedure. Prefer unit
  tests with mocked AWS CLI payloads and, if needed, a manual/local validation
  recipe that tampers with a non-production route target.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #932 |
| --- | --- | --- |
| Portal inspection topology | `platform/terraform/modules/portal/vpc/inspection.tf` | Reuse the existing per-AZ firewall subnet, `sync_states` endpoint map, public/private route matrix, and private-default-via-firewall shape. Do not invent a second portal firewall topology. |
| Portal env roots | `platform/terraform/environments/{dev,prod}/portal/{main,variables,terraform.tfvars,outputs}.tf` | Keep `enable_portal_inspection`, log aggregation, and delete-protection values environment-owned. Add only outputs needed by the assertion, and keep non-secret values typed. |
| Direct NAT route bypass control | `platform/terraform/modules/portal/vpc/main.tf` private `0.0.0.0/0` route count gated by `!var.enable_portal_inspection` | The assertion must prove inspection mode removed the direct private-to-NAT default and replaced it with per-AZ firewall endpoint defaults. |
| Post-apply verifiers | `.github/workflows/_shifter-platform.yml`, `scripts/check_rds_pending_modifications/check_rds_pending_modifications.py` | Put the check after `terraform apply -lock-timeout=5m tfplan`; use bounded polling, clear failures, sanitized output, and unit-testable AWS call wrappers. |
| Portal deploy helper shape | `scripts/portal_deploy/portal_deploy.py` and `scripts/portal_deploy/tests/test_portal_deploy.py` | If the assertion is a helper subcommand, follow the existing `PortalDeployError`, `runner` injection, argparse subcommand, and focused unit-test style. |
| Deploy config binding | `.github/workflows/_shifter-platform.yml`, `docs/dev/deploy-secrets.md`, `TF_VARS_<ENV>_PORTAL` | Deployment-specific enablement still flows through the existing whole-file `local.auto.tfvars` secret or gitignored local override. Do not add a second env parser. |
| Logging and telemetry | `platform/terraform/modules/log-aggregation/`, `module.vpc.firewall_log_group_name`, `enable_log_aggregation` precondition | Keep FLOW/ALERT logs in the existing CloudWatch -> Firehose -> S3/SQS path. Assertion logs should be deploy diagnostics only, not a second telemetry pipeline. |
| IaC and architecture guardrails | `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml` | Terraform/workflow/doc changes must preserve ADR, TFLint, Checkov, and actionlint coverage. New skips or guardrail-file changes require matching ADR docs. |
| Live operator docs | `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/networking.md`, `docs/dev/deploy-secrets.md` | Once implemented, document that inspection is gated by the post-apply assertion and remains alert-only unless a later ADR changes enforcement. |

## Cross-Cutting Layers The Design Must Pass

- GitHub/OIDC auth surface: keep AWS access through
  `aws-actions/configure-aws-credentials` and existing `id-token: write`
  workflow permissions. The assertion must not introduce long-lived AWS keys,
  PATs, extra workflow permissions, or a public callback.
- Secret-handling surface: endpoint IDs, route-table IDs, subnet IDs, firewall
  names, and AZ names are non-secret diagnostics. Do not print rendered
  `local.auto.tfvars`, AWS credentials, Secrets Manager values, SSM secure
  parameters, Guacamole tokens, RDP passwords, SSH keys, signed URLs, or full
  task definitions while troubleshooting the assertion.
- Env-binding shape: `enable_portal_inspection` remains a typed Terraform
  boolean at the portal env root and VPC module boundary. Assertion behavior
  should derive from Terraform outputs or a typed workflow input only if a
  future manual assertion mode is needed. Avoid stringly env vars such as
  `INSPECTION=true` that bypass Terraform intent.
- Terraform/provider validators: keep the existing
  `enable_portal_inspection => enable_log_aggregation` precondition, Terraform
  type checks, saved-plan apply, and state-lock behavior. The assertion is an
  additional post-apply live-state check; it is not a replacement for plan-time
  validation, TFLint, Checkov, or ADR guard.
- AWS live-state validators: call `network-firewall describe-firewall` (or the
  equivalent incumbent AWS CLI shape) for `firewall_status.sync_states` and EC2
  route-table describes for route targets. Validate endpoint IDs, AZ keys,
  attachment health/status, and all route-table entries that make up the public
  to private, private to public, private default, and firewall default paths.
- Routing/security policy layer: when inspection is enabled, private route
  tables must not retain a direct `0.0.0.0/0` NAT route; public/private
  more-specific routes must point to the same-AZ NFW endpoint; firewall route
  tables must point onward to the existing NAT gateway; SG-to-SG and
  CIDR-scoped ingress rules remain least-privilege reachability gates, not the
  inspection proof.
- OS/process exposure: use argv-safe lists in Python or shell with
  `set -euo pipefail` style already used in workflows. Do not pass secrets in
  command arguments, do not enable shell tracing around secret-rendering steps,
  and do not write sensitive Terraform output to side files.
- Error envelope and observability: assertion failures should surface as
  non-zero process exits and GitHub Actions `::error::` diagnostics naming the
  environment, AZ, route table, expected endpoint, observed endpoint, and
  firewall sync state. Keep diagnostics actionable but bounded.

## Extensibility Seam

The seam is a portal-inspection assertion contract over typed Terraform outputs:

- `inspection_enabled`
- firewall name or ARN
- expected firewall endpoint IDs by AZ
- public, private, and firewall route-table IDs by AZ
- public, private, and firewall subnet CIDRs by AZ
- NAT gateway ID when NAT egress is enabled

Add outputs only for non-secret identifiers the assertion needs. This lets a
future staging environment, centralized inspection topology, or enforcement-mode
change reuse the same assertion entrypoint with different expected topology
data, without re-editing workflow shell or inventing a separate policy schema.

If a future change introduces drop enforcement, the parameter belongs at the
portal firewall policy boundary with an explicit value such as `alert-only` vs
`enforce`, plus a matching topology decision. Do not overload
`enable_portal_inspection` to mean both "route through the firewall" and "drop
traffic."

## Gotchas And Anti-Patterns

- Do not leave committed `dev` or `prod` baselines enabling inspection before
  the assertion is a required deploy step.
- Do not treat Terraform's `sync_states` map construction as proof that the
  live routes still point at those endpoints after apply. The acceptance
  criteria require live route/endpoint comparison.
- Do not only check that endpoint IDs are non-empty. The failure mode is stale,
  wrong-AZ, unhealthy, or mismatched endpoint wiring that can blackhole egress.
- Do not validate only the ALB-to-target path and forget private egress. When
  inspection is on, `main.tf` removes the direct private-to-NAT default, so a
  bad NFW endpoint blackholes outbound dependencies.
- Do not make a broken-endpoint test by weakening production routes or adding a
  workflow skip. Keep negative tests isolated, deterministic, and reversible.
- Do not add a duplicate route schema, YAML policy language, exception
  hierarchy, logging framework, or deploy workflow. Existing Terraform,
  workflow, and helper patterns cover the need.
- Do not copy range egress allowlist/drop semantics into the portal firewall.
  Range egress is default-deny by design; portal inspection is currently
  visibility-first because of the per-AZ asymmetric stateful trade-off.
- Do not convert assertion failure into a warning to preserve deploy momentum.
  A green deploy with a blackholed egress path is exactly the failure this issue
  is meant to prevent.

## Non-Goals

- No Terraform implementation, workflow edit, or assertion script in this
  preflight note.
- No change to Cognito/OIDC, Django auth, ALB listener rules, WAF, application
  DTOs, service classes, repositories, migrations, or runtime error envelopes.
- No range egress redesign, GCP/Kubernetes/Helm change, VM-Series appliance,
  Transit Gateway/GWLB centralized topology, or portal-to-range inspection
  expansion.
- No enforcement-mode flip to drop traffic. Alert-only remains the documented
  posture until a later architecture change addresses symmetric stateful
  inspection and operational rollout.
- No new secret store, KMS grant pattern, log bucket, SIEM exporter, or
  deployment-secret mechanism.

## Validation Expectations

For the implementation that follows, run the checks for every touched surface.
For Terraform/workflow/helper changes this should include at least:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
```

Also run `terraform fmt`, targeted `terraform validate` for the edited portal
roots/modules, and the helper unit tests if a script or `portal_deploy.py`
subcommand is added.
