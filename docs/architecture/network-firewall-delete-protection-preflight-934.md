# Network Firewall Delete Protection Preflight (#934)

Status: pre-implementation guidance

Date: 2026-06-14

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/934>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #934 is the shipping
contract: make AWS Network Firewall `delete_protection` an environment-owned
toggle so dev teardown can complete without manual intervention while
production keeps the secure default.

The scope is limited to the two first-party AWS Network Firewall resources:

- Range egress firewall in `platform/terraform/modules/range/vpc/firewall.tf`.
- Portal inspection firewall in `platform/terraform/modules/portal/vpc/inspection.tf`.

Do not change firewall rules, routing topology, log aggregation, KMS ownership,
runtime configuration, or application behavior as part of this lifecycle fix.

## Architecture Decisions

- Treat `delete_protection` as an infrastructure lifecycle setting, not a
  network-security policy. It decides whether Terraform may delete the AWS
  Network Firewall resource; it must not change reachability, inspection,
  egress allowlists, or telemetry.
- Use a narrow typed Terraform boolean at the module boundary and pass an
  explicit environment-root value from dev/prod. The seam should be specific to
  the AWS Network Firewall resource, for example
  `network_firewall_delete_protection` on the range VPC module and a similarly
  scoped portal inspection firewall variable on the portal VPC module.
- Keep the secure default `true` for shared module use and make disposable
  environments opt out explicitly. Dev should set the environment value to
  `false`; prod should set it to `true`.
- Preserve `enable_network_firewall` and `enable_portal_inspection` as separate
  creation toggles. Do not use them as deletion-protection surrogates, and do
  not disable the firewall to make destroy succeed.
- Existing dev firewalls that were created with `delete_protection = true` need
  a Terraform apply that converges the attribute to `false` before destroy. The
  steady-state dev configuration should then create fresh firewalls with delete
  protection already off.
- No new abstraction is warranted for two resource attributes. If a broader
  lifecycle policy emerges later, it can be introduced after more repeated
  shape exists.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #934 |
| --- | --- | --- |
| Range Network Firewall | `platform/terraform/modules/range/vpc/{firewall,variables,outputs}.tf`, `platform/terraform/environments/{dev,prod}/range/{main,variables,terraform.tfvars}` | Add only a scoped boolean and pass it through the existing root-to-module variable path. Keep endpoint outputs and route behavior stable. |
| Portal Network Firewall | `platform/terraform/modules/portal/vpc/{inspection,variables,outputs}.tf`, `platform/terraform/environments/{dev,prod}/portal/{main,variables,terraform.tfvars}` | Reuse the portal VPC module boundary. Keep `enable_portal_inspection`, log aggregation precondition, subnets, routes, and outputs unchanged. |
| Deletion-protection precedent | `platform/terraform/modules/portal/alb/variables.tf`, `platform/terraform/modules/portal/rds/main.tf`, `platform/terraform/modules/guacamole/rds.tf`, `docs/architecture/gcp-cloud-sql-deletion-protection-preflight.md` | Mirror the existing dev false / prod true convention without broadening it into a generic destroy mode. |
| Env binding | `.github/workflows/_range.yml`, `.github/workflows/_shifter-platform.yml`, `docs/dev/deploy-secrets.md`, `platform/terraform/environments/*/*/local.auto.tfvars.example` | Terraform values flow through committed baselines plus gitignored or secret-rendered `local.auto.tfvars`; do not add a new workflow variable or parser. |
| IaC guardrails | `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `docs/adr/exceptions.yaml` | Keep blocking Terraform checks intact. Any new Checkov skip still needs an ADR-004-R11 exception with owner and expiry. |
| Existing firewall policy docs | `docs/architecture/range-egress-ip-allowlist.md`, `docs/architecture/portal-vpc-inspection-preflight-122.md`, `docs/adr/index.yaml` ADR-017 | Do not conflate deletion protection with range egress policy or portal inspection policy. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: this change should not touch Cognito/OIDC, ALB listeners,
  Django auth, CTF auth, or any public/private admin path. A lifecycle toggle
  has no runtime auth contract.
- Secret-handling surface: the toggle is non-secret configuration. It may appear
  in committed tfvars, gitignored `local.auto.tfvars`, plan output, or rendered
  deployment-secret payloads, but it must not introduce Secrets Manager, SSM
  SecureString, KMS grants, or secret values in Terraform variables.
- Env-binding shape: use Terraform `bool` variables. Avoid string parsing,
  environment-name conditionals hidden inside modules, or shell-derived values.
  Dev/prod roots remain the source of environment intent, and operator overlays
  may override them through the existing `local.auto.tfvars` mechanism.
- Terraform/provider validation: Terraform's type system validates the boolean
  shape. The provider applies the attribute on the existing firewall before a
  later destroy. Direct module use should remain secure by default or fail
  explicitly if the module chooses no default.
- Routing and security policy: no firewall policy, rule group, route table,
  subnet, security group, NAT, endpoint output, or engine-provisioner input
  should change. The firewall must remain present in dev; only delete protection
  changes.
- Observability/logging: existing Network Firewall FLOW/ALERT logging,
  CloudWatch log groups, KMS encryption, retention, and log-aggregation paths
  remain canonical. Terraform plan/apply output is sufficient observability for
  this lifecycle setting.
- OS/process exposure: do not add AWS CLI break-glass commands, destroy prehooks,
  or command-line secret material. Existing workflows render HCL payloads to
  files and run Terraform; keep that model.
- Error envelope: failures should surface as Terraform validate/plan/apply or
  provider errors. Do not add Django exceptions, API error envelopes, service
  classes, or repositories for infrastructure deletion protection.

## Extensibility Seam

The seam is the resource-scoped boolean at each Terraform module boundary, fed
by explicit environment-root values. A future staging, event, or ephemeral
environment can choose its own value in tfvars or `local.auto.tfvars` without
editing the module.

If AWS Network Firewall policy-change or subnet-change protections become a
future requirement, add separate narrowly named booleans for those AWS
attributes. Do not overload this `delete_protection` toggle or introduce a
generic `allow_destroy`, `break_glass`, or `environment_mode` abstraction.

## Gotchas And Anti-Patterns

- Do not assume `terraform destroy` will first update a protected live firewall.
  Existing dev resources need a successful apply with delete protection disabled
  before the first clean destroy.
- Do not confuse AWS Network Firewall `delete_protection` with RDS
  `deletion_protection`, ALB `enable_deletion_protection`, Cognito
  `deletion_protection`, Terraform `prevent_destroy`, backups, retention, or
  final snapshots.
- Do not make dev teardown work by setting `enable_network_firewall = false`,
  `enable_portal_inspection = false`, removing route outputs, or deleting the
  firewall from state.
- Deployment secrets render whole-file `local.auto.tfvars` overlays. If an
  operator overlay already pins the new value, it wins over committed tfvars;
  keep docs/examples aligned so dev overlays do not accidentally re-enable
  protection.
- Do not add inline Checkov skips or weaken `.checkov.yaml`, `.tflint.hcl`, CI,
  or ADR guardrails to make a variableized resource pass.
- Do not commit real account-local `local.auto.tfvars` files or broaden the
  deployment-secret payload surface beyond existing Terraform HCL values.

## Non-Goals

- No root `shifter.yaml` setting, installation parser, schema, DTO, controller,
  service, repository, exception hierarchy, or runtime logging path.
- No change to range egress allowlists, portal inspection rules, Suricata rule
  ordering, firewall logging, KMS keys, route tables, VPC peering, NAT, S3/SSM
  endpoints, or engine-provisioner firewall endpoint consumption.
- No GCP, Kubernetes, Helm, bootstrap, Packer, or application implementation.
- No new destroy workflow, manual AWS CLI teardown step, state surgery, rebase,
  force-push, or protected-branch operation.
- No Ground Control requirement work; this issue is the authoritative contract.

## Validation Expectations

For the implementation change, run the repo-required checks for touched
surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run Terraform formatting and targeted validation for every edited AWS root
or module, such as the dev/prod range and portal roots. If workflows are
changed, run `actionlint`.
