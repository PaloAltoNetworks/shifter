# Portal VPC Inspection Preflight (#122)

Status: pre-implementation guidance

Date: 2026-05-29

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/122>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #122 is the shipping
contract: add an inline inspection and microsegmentation boundary for the AWS
portal VPC so traffic between the public ALB tier and internal portal services
is logged and inspectable before production handoff.

Do not implement the issue in this note. The implementation that follows must
design against the existing AWS portal Terraform, telemetry, secret, and CI
guardrails rather than adding parallel infrastructure concepts.

## Architecture Decisions

- Use AWS Network Firewall as the default portal inspection mechanism for this
  issue. It is the repo's existing managed AWS inspection primitive, already
  modeled in `platform/terraform/modules/range/vpc/firewall.tf`, and it avoids
  adding a VM-Series/PAN-OS bootstrap, licensing, Secrets Manager, and operator
  management surface to the portal boundary.
- The portal firewall is a portal-owned boundary. Reuse range-side Network
  Firewall patterns for Terraform shape, logging, KMS, and route-table hygiene,
  but do not reuse range concepts such as Kali, victim, XDR egress allowlists,
  NGFW bypass, or range VPC route outputs.
- Inspection must be route-backed. Create a dedicated portal firewall subnet
  tier and route the protected flows through firewall endpoints with symmetric
  return paths. Do not claim inspection for traffic that stays in one subnet,
  bypasses route tables, or cannot be proven to return through the same
  stateful inspection path.
- Keep WAF at the public ALB, but treat it as north-south HTTP protection only.
  WAF, ALB access logs, VPC Flow Logs, and RDS logs are telemetry layers; they
  are not substitutes for the inline east-west inspection boundary.
- Logging and alerting must feed the existing `log-aggregation` module and
  shared alerting conventions. New firewall log groups should be emitted as
  module outputs and included in the environment root's `source_log_group_names`
  so CloudWatch -> Firehose -> S3/SQS stays the single telemetry pipeline.
- The current committed portal tfvars set `enable_alb_access_logs`,
  `enable_vpc_flow_logs`, `enable_rds_log_exports`, and `enable_waf_logging` to
  true while `enable_log_aggregation` is false. The implementation must make
  production telemetry fail closed: either enable aggregation for production or
  add Terraform validation so per-source logging cannot silently degrade to
  empty destinations.
- Tighten microsegmentation with security-group-to-security-group rules where
  the repo already has the pattern. Guacamole RDS and engine provisioner RDS
  access already use SG references; portal RDS and Redis should not keep broad
  `allowed_cidr_blocks = [module.vpc.vpc_cidr]` as the final posture if the
  work claims microsegmentation.
- LibreChat is named in the issue, but this repo currently has no canonical
  LibreChat Terraform module. If the implementation adds one, model it as a
  named portal internal service with its own security group, log group, subnet
  placement, secrets contract, and inspection attachment. Do not introduce a
  generic "internal service" schema only to hide a single concrete service.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #122 |
| --- | --- | --- |
| AWS portal root | `platform/terraform/environments/{dev,prod}/portal/main.tf` and `variables.tf` | Wire the inspection module through both env roots consistently; keep env-specific values in tfvars or `local.auto.tfvars`. |
| Portal network ownership | `platform/terraform/modules/portal/vpc/` | Add portal subnet/route-table outputs at the VPC boundary; do not put portal routing in app modules. |
| Public edge | `platform/terraform/modules/portal/alb/` | Preserve HTTPS listener, `/admin` fixed-response block, WAF association, access-log contract, and target-group ownership. |
| Django compute | `platform/terraform/modules/portal/ec2/` | Preserve private-only EC2/ASG, IMDSv2, CloudWatch awslogs, SSM bootstrap, and secret-ARN handoff. |
| Data plane | `platform/terraform/modules/portal/rds/`, `portal/redis/`, `modules/guacamole/` | Reuse existing RDS/Redis/Guacamole resource boundaries and SG-reference patterns; do not duplicate database/cache modules. |
| Existing inspection pattern | `platform/terraform/modules/range/vpc/firewall.tf` | Reuse AWS Network Firewall resource/logging/KMS patterns only; keep portal rules portal-specific. |
| Telemetry pipeline | `platform/terraform/modules/log-aggregation/` | Add firewall logs through existing CloudWatch subscription/Firehose/S3/SQS outputs, not a second bucket or SIEM exporter. |
| KMS for logs and secrets | module-local CloudWatch CMKs, `kms_cw_logs.tf`, portal Secrets Manager CMK | New log groups need CMK-backed retention; new secret readers must satisfy ADR-004-R10. |
| Runtime secret hydration | `platform/terraform/modules/portal/ssm/`, `portal/ec2/user_data.sh`, `shifter/shifter_platform/entrypoint.sh`, `entrypoint-lib.sh` | SSM stores non-secret references; secret values come from Secrets Manager at container start and must not ride in Terraform vars or process argv. |
| Terraform guardrails | `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml` | Blocking Checkov/TFLint posture applies; new skips require ADR-004-R11 exceptions with owner and expiry. |
| Architecture checks | `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.github/workflows/deploy.yml` path filters | Terraform and docs changes must keep CI routing and ADR guard coverage intact. |
| Product docs | `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/networking.md` | Update the live networking/threat-model docs when the boundary lands; deprecated docs are not the source of truth. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: keep Cognito/OIDC as the AWS portal authentication boundary and
  keep the ALB `/admin` deny rule intact. The inspection layer must not create
  a new public admin path, bypass listener, private debug endpoint, or alternate
  auth flow.
- Secret-handling surface: AWS Network Firewall should require no new runtime
  secret. If a later third-party appliance or LibreChat service needs a token,
  store the value in Secrets Manager under the portal CMK, pass only secret
  ARNs through SSM/terraform outputs, and extend the KMS grant checker scope
  when a new role reads portal-CMK secrets.
- Env-binding shape: required Terraform inputs belong in the portal env roots
  and module `variables.tf` with explicit types and validation. Deployment
  values continue to flow through `TF_VARS_<ENV>_PORTAL` or gitignored
  `local.auto.tfvars`, not committed real operator values.
- Terraform validation: CIDRs, subnet selections, feature toggles, and logging
  dependencies must fail at `terraform validate`/plan time. In particular,
  `enable_*_logging = true` with no aggregation destination must not be a
  successful production shape.
- Routing/security policy: use dedicated firewall subnets and exact route-table
  entries for protected subnet CIDRs. Preserve symmetric routing for stateful
  inspection, especially across AZs, ALB target placement, RDS failover, and
  Guacamole ECS tasks. Keep SGs as least-privilege enforcement even when the
  firewall is present.
- OS/process exposure: do not put secret values, firewall rule payloads that
  contain credentials, or appliance bootstrap authcodes into user-data command
  lines, Docker `-e` values, process argv, or cloud-init logs. Non-secret ARNs,
  log group names, subnet IDs, and SG IDs may remain configuration.
- Observability/logging: new Network Firewall FLOW and ALERT logs must use
  CloudWatch log groups with retention and KMS, and must be subscribed through
  `log-aggregation` when aggregation is enabled. Alerting should use the
  existing SNS/alarm pattern rather than a bespoke notification path.
- Error envelope: this is infrastructure work. Expected failures should surface
  through Terraform validation, plan/apply failures, Checkov/TFLint, and ADR
  guard. Do not add Django exception classes or user-facing error envelopes
  unless the implementation genuinely adds an application runtime surface.

## Extensibility Seam

The durable seam is a portal-owned inspection attachment contract: named subnet
tiers, route-table outputs, security-group inputs, and firewall log-group
outputs. A future internal service such as LibreChat should join that contract
by contributing its service subnet/security group/log group to the portal env
root, without editing the telemetry pipeline or adding a second inspection
abstraction.

Keep the enablement knob environment-owned, such as `enable_portal_inspection`.
Per-service rule variation belongs as narrowly typed Terraform inputs on the
portal inspection/VPC boundary, not as a root application schema, Django model,
or duplicated YAML policy language.

## Gotchas And Anti-Patterns

- Do not conflate security groups with inspection. SGs decide reachability;
  they do not provide payload visibility, alert logs, or a routeable inspection
  boundary.
- Do not conflate VPC Flow Logs with inline inspection. Flow logs are required
  telemetry, but they cannot block or perform stateful rule evaluation.
- Do not route protected services and their clients into the same subnet and
  then claim east-west inspection. Same-subnet traffic is the common bypass
  class for route-table-based firewalls.
- Do not ignore asymmetric routing. Stateful inspection can fail or silently
  miss return traffic if cross-AZ routes, ALB target selection, RDS failover,
  or ECS task placement send each direction through different endpoints.
- Do not claim portal-to-range peering traffic is covered by the new portal
  firewall unless the implementation explicitly routes and validates it. The
  issue is portal VPC defense-in-depth, independent of range-side controls.
- Do not copy range firewall allowlist rules into the portal. Portal service
  traffic is not Kali/victim egress and should not inherit XDR egress language,
  PANW allowlists, or NGFW licensing bypasses.
- Do not add a parallel log bucket, SQS queue, SIEM connector, KMS key policy
  pattern, exception format, or workflow path filter if the existing
  log-aggregation and ADR machinery covers it.
- Do not add Checkov inline skips without matching `docs/adr/exceptions.yaml`
  entries. The repo's Terraform Checkov gate is blocking by design.
- Do not make production depend on example.com committed tfvars. Real values
  still come from GitHub secrets or gitignored local overrides.

## Non-Goals

- No application feature work, Django DTO/schema work, database migrations, or
  new business-service abstractions.
- No change to Cognito/OIDC auth, CTF participant auth, Django admin policy, or
  risk-register audit schema.
- No GCP implementation, Kubernetes NetworkPolicy change, or Helm chart change
  unless the issue scope is explicitly expanded.
- No range-side redesign, range egress policy change, or reuse of persistent
  per-user VM-Series NGFW infrastructure for the portal.
- No new secret hierarchy, exception hierarchy, validation framework, logging
  framework, or workflow engine.

## Validation Expectations

For the implementation change, run the repo-required architecture checks for
all touched surfaces. At minimum for AWS portal Terraform plus docs:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run `terraform fmt`, `terraform validate`, and Checkov through the
repo-standard hooks/CI path for any touched Terraform roots or modules. Run
`actionlint` if workflow path filters change, and update ADR exceptions/docs in
the same PR if any new guardrail waiver is introduced.
