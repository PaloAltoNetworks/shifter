# Range Zero-Egress Posture Preflight (#1171)

Status: pre-implementation guidance

Date: 2026-06-30

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1171>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #1171 is the shipping
contract: add an optional commercial self-serve range posture where participant
subnets have no default-route path to the internet. This note does not
implement Terraform, Packer, provisioner, or smoketest changes.

## Architecture Decisions

- The new posture is a route-table posture, not another firewall allowlist. In
  `none` mode, runtime range subnet route tables must not receive a
  `0.0.0.0/0` route to Network Firewall, NAT, or an Internet Gateway. The
  existing event posture remains `allowlist`.
- Do not overload ADR-017 `deny-all`. `deny-all` is still a firewall-enforced
  egress policy with a default route and documented exception lanes; zero
  egress is "no default route exists."
- Keep security groups as ingress gates. Do not move internet containment into
  per-range security-group egress rules; that would duplicate and weaken the
  existing ADR-020 ownership split.
- If the mode becomes operator-facing, extend the existing
  `settings.range_egress` contract and renderer path. Do not add a second
  public egress schema in Terraform tfvars, workflow inputs, Django settings,
  or shell snippets.
- The runtime AWS Terraform module may carry an internal `egress_mode`
  bridge (`allowlist` or `none`) because it owns per-range route creation. That
  bridge must be validated and fed through the existing ECS env ->
  `terraform_vars.py` -> `terraform.tfvars.json` path, not inferred from an
  empty firewall endpoint.
- Stable range VPC service endpoints are a separate decision from public
  internet egress. SSM endpoints may remain management-plane plumbing for Run
  Command if the commercial shape still uses provisioner-driven bootstrap, but
  S3, STS, Bedrock, Route 53 Resolver, or any other endpoint reachable from
  participant subnets must be explicitly allowed, explicitly disabled, or
  documented as a management exception. Do not leave the existing S3 gateway
  route association enabled in `none` mode by accident.
- Runtime package/tool/agent downloads must move to image bake or in-range
  service paths. Packer may use internet access while baking AMIs; first boot
  and setup plans for a `none` range must not depend on public apt, npm, pip,
  GitHub, S3 public endpoints, XDR/XSIAM service URLs, DNS, or NTP.
- Victim telemetry for the commercial shape must be one of two explicit
  postures: omitted, or sent through a dedicated proxy outside participant
  subnets. Do not give range subnets an internet route just for XDR/XSIAM.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #1171 |
| --- | --- | --- |
| Range isolation model | ADR-020, `docs/architecture/range-isolation-model.md` | Extend the route-table model; keep SG ingress and internet egress responsibilities separate. |
| Range egress policy schema | ADR-017, `shifter/installation/range_egress.py`, `loader.py`, `render.py` | Reuse the root policy and `InstallationConfigError` surface for operator-facing mode changes. |
| AWS stable range VPC | `platform/terraform/modules/range/vpc/{firewall,nat,s3-endpoint,ssm-endpoints,dns_resolver,outputs}.tf` | Preserve allowlist mode; explicitly decide which endpoint paths exist in the commercial shape. |
| Runtime range networking | `shifter/engine/provisioner/terraform/modules/range/{variables,main,outputs}.tf` | Gate only the runtime `aws_route.firewall` default route in `none`; avoid NAT fallback. |
| Provisioner env binding | `platform/terraform/modules/engine-provisioner/{variables,task_definition}.tf`, `shifter/engine/provisioner/config.py`, `terraform_vars.py` | Carry any route posture as a typed value through the existing env/tfvars path with tests. |
| Terraform runner hygiene | `shifter/engine/provisioner/terraform_base.py` | Keep mode values in the staged `terraform.tfvars.json` path; do not pass sensitive URLs or config in argv. |
| Runtime setup plans | `instance_setup.py`, `plans/linux_xdr_agent_install.py`, `plans/xdr_agent_install.py`, `plans/*bootstrap*.py` | Make `none` mode avoid public downloads and fail closed when required runtime artifacts are unavailable. |
| AMI bake | `shifter/packer/*.pkr.hcl`, `shifter/packer/scripts/**`, `shifter/packer/tests/test_packer.py` | Bake required packages, tools, and agents; keep Packer validation/tests as the package-install guard. |
| Scenario isolation tests | `scenario-dev/polaris/tests/isolation-smoketest.sh`, `scripts/terraform/tests/test_range_firewall_dns.py` | Extend the existing smoketest style and add static route invariants where live AWS assertions are not available. |
| Repo guardrails | `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `docs/adr/exceptions.yaml` | Run ADR guard; do not commit live CIDRs, account IDs, generated state, or weakened checks. |

## Cross-Cutting Layers

- Auth surface: no Django, Cognito, CTF participant auth, Guacamole, GitHub
  OIDC, or API-token behavior should change. If commercial posture selection
  later becomes a portal/API feature, it must use the existing controller,
  serializer, service, audit, and auth boundaries for that domain.
- Secret-handling surface: egress modes and CIDR/domain examples are
  configuration, not secrets. Presigned agent URLs and installer credentials are
  sensitive runtime artifacts; `none` mode should avoid creating them for
  guests, and any remaining management-side use must not be logged, committed,
  passed in shell strings, or leaked through Terraform output.
- Env-binding shape: public operator intent belongs in `shifter.yaml` through
  `load_root_config` and the range-egress renderer. Runtime module inputs are
  bridge variables. Terraform variable validation remains the direct-use
  backstop for operators who bypass the renderer.
- Terraform/security policy: allowlist mode keeps `aws_route.firewall` and the
  Network Firewall STRICT_ORDER default-deny. `none` mode must omit the
  runtime default route and must not fall back to `private_to_nat`,
  `enable_network_firewall = false`, or route-table inheritance that restores
  a default route.
- OS/runtime exposure: route tables, DHCP/resolver behavior, SSM Run Command,
  user data, Packer scripts, guest package managers, XDR installers, Claude
  Code/Bedrock config, and simulated phone-home flows all see the artifact.
  First boot in `none` mode must be functional without public DNS or internet.
- Error envelope: root config failures should raise `InstallationConfigError`;
  provisioner setup failures should use the existing setup/provisioning error
  paths; Terraform failures should come from variable validation, lifecycle
  preconditions, plan/apply, or focused static tests. Do not add a new Django
  exception hierarchy for this infrastructure posture.
- Logging/observability: Network Firewall logs remain allowlist-mode evidence.
  In `none` mode the evidence surface is route-table state, VPC flow logs if
  enabled, Terraform/static tests, and the isolation smoketest. Logs must use
  existing redaction helpers for sensitive IDs and must not print installer
  URLs or live cloud identifiers.
- Validation gates: for implementation, run ADR guard, Terraform fmt/validate
  and TFLint for touched Terraform, provisioner/Packer unit tests for touched
  Python or bake scripts, and `actionlint` for workflow edits.

## Extensibility Seam

The seam is an explicit range egress route posture, parameterized as a mode.
At minimum the AWS runtime module needs `egress_mode = "allowlist" | "none"`.
If the mode is operator-facing, the public seam should be the existing
provider-neutral `RangeEgressPolicy` and renderer, extended with a distinct
no-internet value and backend support checks. Future variants such as
`proxy`, per-scenario posture, or named commercial profiles should add values
or policy fields at that seam rather than editing route resources and setup
plans independently.

## Gotchas And Anti-Patterns

- Do not treat an empty `firewall_endpoint_id` as zero egress. Today that shape
  can mean "firewall disabled" or a miswired environment; `none` needs an
  explicit mode.
- Do not make `enable_network_firewall = false` a production shortcut. It
  currently creates direct NAT egress in the stable private route table.
- Do not leave the runtime S3 gateway association, STS/Bedrock private
  endpoints, or Resolver allow rules as accidental participant egress in `none`
  mode. Each retained path needs a threat-model statement.
- Do not conflate zero-egress with DNS hardening (#1172), the CIDR allowlist
  (#775/#958), NGFW licensing bypasses, portal VPC inspection, Kubernetes
  NetworkPolicy, or GCP/GDC VM Runtime egress.
- Do not require operators to maintain the same mode in both `shifter.yaml` and
  `*.auto.tfvars`.
- Do not commit live CIDRs, project IDs, account IDs, VPC/subnet IDs, endpoint
  IDs, route table IDs, real deployment domains, installer URLs, or generated
  Terraform/Packer artifacts.
- Do not rely only on unit/static tests. The acceptance criteria require an
  inside-the-range connectivity assertion that previously allowed lanes
  (victim CIDRs, DNS, NTP) are unreachable in `none`.
- Do not make Packer bake-time internet dependencies part of range runtime
  correctness. Baked images must boot with everything needed for the selected
  posture.

## Non-Goals

- No Terraform, Packer, provisioner, workflow, or smoketest implementation in
  this preflight note.
- No change to existing event/allowlist behavior.
- No multi-VPC-per-range redesign, multi-AZ placement redesign, or replacement
  of ADR-017/ADR-020.
- No new application API, DTO, service, repository, persistence model, Django
  setting, auth rule, or logging framework.
- No claim that all AWS private service endpoints are internet egress; the
  point is that they must be deliberately classified for the commercial shape.

## Validation Expectations

For the implementation change, run the repo-required gates for touched
surfaces. At minimum for architecture and Terraform edits:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run Terraform formatting/validation for edited roots, targeted
provisioner/Packer tests, a Polaris isolation smoketest or documented live-range
equivalent, and `actionlint` for workflow changes.
