# Range DNS Egress Resolver Preflight (#1172)

Status: pre-implementation guidance

Date: 2026-06-29

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1172>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #1172 is the shipping
contract: close the DNS-based exfiltration / C2 lane created by allowing range
hosts to query a public recursive resolver, while preserving required in-range
and scenario-required name resolution.

This note is not an implementation plan and does not change Terraform,
firewall policy, DHCP, guest configuration, or tests.

## Architecture Decisions

- Keep AWS Network Firewall as the single internet egress control plane. Do not
  move partial DNS egress policy into per-range security-group egress rules.
- Replace the public-recursive DNS lane with an in-range resolver path. The
  firewall should allow UDP/TCP 53 only to the resolver endpoint(s) that are
  part of the range control plane, then drop all other DNS egress before the
  default-deny.
- The resolver is platform/range infrastructure, not merely a scenario DNS
  sidecar. Scenario DNS containers can serve internal training zones, but they
  are not sufficient as the VPC egress boundary unless every range host and
  nested workload is forced through them and direct resolver egress is blocked.
- Resolver policy should be allow/refuse by name, not forward-all. It may answer
  in-range hostnames, scenario-owned zones, documented victim domains required
  by the exercise, and provider-private service names required for bootstrapping.
  Unknown external names must be refused or sinkholed.
- Do not reuse `settings.range_egress.allowed_cidrs` for DNS names. Existing
  `range_egress` is an IP CIDR policy with CIDR validators and renderer
  semantics. If operator-configurable DNS policy is needed, introduce a
  separate shape rather than overloading the CIDR allowlist mode.
- Query logging and rate limiting are part of the security posture for
  untrusted users. Logs should be retained and encrypted consistently with the
  existing Network Firewall / VPC logging conventions, and should avoid leaking
  secrets or internal topology into public issue/PR text.
- The Polaris smoketest should prove both sides of the contract from inside the
  range: required in-range names still resolve, and an arbitrary external
  canary domain fails to resolve.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #1172 |
| --- | --- | --- |
| Range isolation model | ADR-020 in `docs/adr/index.yaml`, `docs/architecture/range-isolation-model.md` | Preserve the routing + Network Firewall default-deny ownership model. Update the DNS section when behavior changes. |
| Range egress IP policy | ADR-017, `docs/architecture/range-egress-ip-allowlist.md`, `shifter/installation/range_egress.py` | Reuse the vocabulary for IP egress, but do not extend its CIDR schema to domain resolver policy. |
| AWS range VPC | `platform/terraform/modules/range/vpc/{main,firewall,variables,outputs}.tf` | Stable range infrastructure owns resolver resources, firewall rule ordering, logging, DHCP options, and outputs consumed by runtime provisioning. |
| AWS range env roots | `platform/terraform/environments/{dev,prod,proof}/range/{main,variables,terraform.tfvars}` | Environment roots pass provider variables into the module. Keep deployment-specific resolver addresses/domains out of committed tfvars unless they are examples/placeholders. |
| Runtime range module | `shifter/engine/provisioner/terraform/modules/range/{main,variables}.tf` | Runtime subnets and routes must continue to send internet-bound traffic through the firewall endpoint; avoid per-range SG egress policy as the DNS fix. |
| Provisioner env binding | `platform/terraform/modules/engine-provisioner/task_definition.tf`, `shifter/engine/provisioner/config.py`, `terraform_vars.py` | If runtime Terraform needs resolver metadata, add a typed env/variable handoff beside existing `FIREWALL_ENDPOINT_ID`, `S3_ENDPOINT_ID`, and range-network fields. |
| Polaris DNS path | `scenario-dev/polaris/tests/isolation-smoketest.sh`, `shifter/engine/provisioner/plans/_polaris_scripts.py`, `scripts/polaris-aws-range/a2_setup.ps1` | Scenario DNS and DC forwarders must align with the VPC resolver policy; do not prove only Docker-local DNS behavior. |
| Logging/encryption | `platform/terraform/modules/range/vpc/firewall.tf`, `main.tf`, `kms.tf` | Follow existing CloudWatch log group, KMS, and retention conventions for any resolver query logs. |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, `.gc/plan-rules.md`, `docs/adr/exceptions.yaml` | Run ADR guard for architecture changes; new guardrails or exceptions require ADR registry updates. |

## Cross-Cutting Layers

- Auth surface: no Cognito, Django, CTF participant auth, Guacamole, or GitHub
  OIDC behavior should change. DNS policy is infrastructure reachability, not
  an application authorization decision.
- Secret-handling surface: resolver IPs, zone names, domain allowlists, and
  rate limits are configuration, not secrets. Do not put them in Secrets
  Manager, Kubernetes Secrets, or runtime secret env vars. Do not commit live
  deployment CIDRs or resolver addresses; use placeholders or generated
  Terraform outputs.
- Env-binding shape: if the resolver address must reach runtime provisioning,
  propagate it through Terraform outputs and the existing ECS task env /
  `RangeConfig` path. Avoid a second YAML parser, Django setting, or shell
  string convention for resolver metadata.
- Config validation: DNS policy needs its own validation if it becomes
  operator-configurable. Validate domain/zone syntax, reject empty allowlists in
  enforce mode, reject wildcard/forward-all semantics, and keep Terraform
  validation as a direct-use backstop. Do not duplicate CIDR validators from
  `RangeEgressPolicy` for names.
- Terraform/security policy: preserve STRICT_ORDER rule intent. Resolver allow
  rules must be before `drop_all`; all public resolver UDP/TCP 53 paths must be
  absent. If `enable_network_firewall = false`, direct NAT remains a bypass and
  must not be represented as a protected posture.
- OS-level exposure: DHCP option sets, guest `resolv.conf`, Windows DNS
  forwarders, and Docker container resolvers all see this artifact. Prefer
  declarative Terraform/guest-bootstrap contracts over ad hoc manual edits, and
  do not pass credentials or tokens in argv while changing bootstrap scripts.
- Error envelope: infrastructure failures should surface through Terraform
  validation/plan/apply or existing provisioner failure paths. Do not add a
  Django exception hierarchy, API DTO, service, or repository for this issue.
- Observability: Network Firewall FLOW/ALERT logs, VPC flow logs when enabled,
  and resolver query/rate-limit logs are the evidence surface. Application logs
  should not become the source of truth for DNS containment.
- Test surface: extend the existing Polaris bash smoketest style for runtime
  behavior and add targeted Terraform/static tests only if needed to prevent
  public resolver rules from reappearing.

## Extensibility Seam

The immediate seam belongs at the stable range VPC module: resolver endpoint,
resolver policy inputs, firewall allow rule, DHCP option set, logs, and outputs.
If the policy becomes operator-configurable, use a separate provider-neutral
`range_dns`-style settings block with allowed zones/domains and enforcement mode,
then render provider bridge variables from that validated shape. Future
scenario-level DNS requirements should extend that policy or a scenario-owned
allowed-zone list; they should not require editing the canonical firewall policy
for every scenario.

## Gotchas And Anti-Patterns

- Do not solve this by changing the allowed destination from one public resolver
  to another public resolver. Destination-IP allowlisting does not constrain
  QNAME content.
- Do not forward unknown names to a public resolver or the Amazon VPC resolver
  by default. The Amazon resolver is valid only behind explicit conditional
  forwarding for private AWS service names that the range needs.
- Do not rely solely on the Polaris Docker `dns` container. The acceptance
  criteria are about range egress, including direct UDP/TCP 53 from range hosts.
- Block both UDP and TCP 53. DNS tunneling and large responses can use TCP.
- Check IPv6 if any range path enables it; an IPv4-only DNS drop is not a full
  public-resolver control if IPv6 egress exists.
- Windows DC DNS forwarders are part of the resolver chain. If the DC remains a
  resolver for `boreas.local`, it must not become a forward-all tunnel to a
  recursive resolver.
- Keep the NGFW subnet bypass separate. Do not place participant resolvers or
  scenario DNS in a subnet covered by the all-egress NGFW bypass.
- Do not conflate DNS containment with the separate NTP allow lane, SNI/domain
  allowlists, CIDR allowlists, GCP/GDC VM Runtime nameservers, Kubernetes
  NetworkPolicies, or application SSRF DNS pinning.
- Do not commit live CIDRs, resolver IPs, account-specific endpoint names, or
  real deployment domains in docs, tfvars, tests, or examples.

## Non-Goals

- No Terraform, DHCP, resolver, firewall, guest-bootstrap, or smoketest
  implementation in this preflight note.
- No change to security group egress posture, NAT topology, portal VPC
  inspection, persistent VM-Series NGFW policy, Kubernetes NetworkPolicy, or
  GCP/GDC range DNS behavior unless a follow-up issue explicitly expands scope.
- No new application API, Django setting, DTO, service, repository, persistence
  model, exception hierarchy, or logging framework.
- No replacement of ADR-017 range IP egress policy or `RangeEgressPolicy`.
- No claim that `enable_network_firewall = false` is protected by this DNS
  design.

## Validation Expectations

For the implementation change, run the repo-required checks for touched
surfaces. At minimum for architecture and Terraform edits:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run Terraform formatting/validation for edited roots, the Polaris
isolation smoketest or a syntax-preserving equivalent when the live range is not
available, and `actionlint` for workflow changes.
