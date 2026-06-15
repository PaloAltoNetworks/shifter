# GCP VPC Firewall Preflight

Issue: GitHub #959, "[HIGH] No firewall rules defined on GCP VPCs".

This note records the architecture boundary for adding explicit GCP VPC
firewall policy. It is intentionally not an implementation plan; the goal is
to keep the upcoming Terraform change inside existing platform, range, and
runtime contracts.

## Decision

The GCP platform foundation must make VPC reachability explicit in Terraform
instead of relying on provider defaults or project history. `platform-core`
owns the shared GCP platform VPC, dedicated peered range VPC, GKE subnet,
private service networking, NAT, and the provider-neutral range-network
outputs consumed by the provisioner runtime. Firewall rules for those VPCs
belong at that same boundary unless a later ADR splits networking into a
separate module.

The baseline posture is:

- Range VPC ingress is denied by default with explicit, higher-priority allows
  only for platform-origin traffic required by the provisioner and participant
  access path.
- Platform VPC ingress is explicit and limited to required platform sources:
  GKE/node control traffic, Google health checks where needed by GKE ingress,
  private service access, and any documented operator/IAP source.
- SSH and RDP are never opened from `0.0.0.0/0` or broad external CIDRs. If
  direct VM admin access is ever required, it uses a narrow, environment-owned
  source allowlist or IAP-only source CIDRs, not a module default.
- Every intentional broad source or port range is named in Terraform and
  justified beside the resource or variable contract.

GCP custom VPC nuance: the current module creates custom networks with
`auto_create_subnetworks = false`. GCP's permissive `default-allow-internal`,
`default-allow-ssh`, `default-allow-rdp`, and `default-allow-icmp` rules are a
default-network baseline, not rules automatically attached to every custom VPC.
Do not conflate this issue with deleting project default-network rules unless
the implementation also adds a project-baseline control that explicitly owns
that network and its lifecycle.

## Canonical Incumbents

- `platform/terraform/gcp/modules/platform-core/main.tf`: owns the platform
  and range VPCs, peering, GKE subnet, Cloud NAT, Cloud Armor, private service
  networking, and GKE cluster.
- `platform/terraform/gcp/modules/platform-core/variables.tf`: canonical
  module input validation layer for GCP network/security inputs.
- `platform/terraform/gcp/environments/gcp-dev/main.tf` and
  `variables.tf`: environment-level input seam. Environment roots pass values
  into `platform-core`; avoid hardcoding operator or environment-specific CIDRs
  in the module.
- `platform/terraform/gcp/modules/platform-core/outputs.tf` and
  `platform/terraform/gcp/environments/gcp-dev/outputs.tf`: provider-neutral
  range-network output contract consumed by runtime renderers and the
  provisioner.
- `scripts/gcp/render_runtime_env.py` and
  `shifter/shifter_platform/engine/ecs.py`: runtime propagation contract for
  `RANGE_NETWORK_ID`, `RANGE_NETWORK_CIDR`, `RANGE_NETWORK_REGION`, and
  `PORTAL_NETWORK_CIDRS`. Do not introduce a second runtime schema for network
  inventory.
- `scripts/bootstrap/deploy.py`: existing GCP IAP source constant and argv-array
  gcloud invocation style for bootstrap-owned operator access.
- `docs/architecture/gke-control-plane-access-preflight.md` and ADR-008:
  precedent for fail-closed GCP network/security inputs at both Terraform and
  bootstrap boundaries.
- `platform/terraform/modules/range/vpc/firewall.tf`: AWS range-network
  precedent for allowlist-first, default-deny intent. Reuse the security
  posture, not the AWS-specific implementation shape.
- `scripts/check_tf_sg_cidrs/check_tf_sg_cidrs.py`: existing AWS-only ingress
  CIDR lint precedent. If GCP firewall policy becomes a recurring source of
  regressions, extend policy enforcement intentionally rather than adding an
  ad hoc checker in the Terraform module.
- `.tflint.hcl`: stack-native Terraform lint entrypoint with the Google ruleset.

## Cross-Cutting Layers

Security layers the design must satisfy:

- Terraform resource policy: express ingress and any exceptional egress with
  `google_compute_firewall` or the repo-selected GCP firewall resource at the
  `platform-core` boundary. Do not rely on implied GCP rules as the documented
  security posture.
- Terraform input shape: new configurable source CIDRs or port sets, if any,
  belong in `platform-core/variables.tf` and are passed from environment roots.
  Keep CIDR variables typed as `list(string)` or structured object lists with
  validation; do not embed environment IPs in locals.
- Terraform validation: reject empty allowlists where a public or
  cross-network access path would otherwise be created, reject malformed CIDRs,
  and reject `0.0.0.0/0` / `::/0` for SSH, RDP, and range ingress.
- Runtime env-binding: keep the existing range-network contract rendered by
  `scripts/gcp/render_runtime_env.py` and forwarded by
  `_GCP_PROVISIONER_ENV_KEYS`; firewall outputs should not be needed by the app
  unless a future provisioner feature truly consumes them.
- Auth and operator access: use the existing IAP/source-CIDR convention for
  operator paths. Do not reintroduce public SSH/RDP as an authentication or
  break-glass surface.
- Secret handling: firewall CIDRs and ports are configuration, not secrets. Do
  not put them in Secret Manager, Kubernetes Secrets, or runtime secret bundles.
- OS/process exposure: Terraform/gcloud invocations may carry CIDRs and rule
  names in argv; credentials and tokens must stay in the existing GCP auth
  path and not be embedded in shell strings or command-line flags.
- Error handling: fail through Terraform variable validation, Terraform
  plan/apply errors, and the existing bootstrap `error(...)` path if bootstrap
  validation is extended. Do not add an application exception hierarchy for
  infrastructure firewall policy.
- Observability: rely on Terraform plan/apply diffs for rule intent and enable
  GCP firewall logging only when it is deliberately required for security
  evidence or troubleshooting; application logging must not become the source
  of truth for VPC reachability.

## Extensibility Seam

The seam for future variation is the environment-owned allowlist contract for
sources and required service ports, with `local.portal_network_cidrs` remaining
the canonical platform-origin CIDR set for provisioner traffic into the range
VPC. One obvious future change is adding a bastion/IAP-only operator path or a
new provisioner protocol; that should extend the structured allowlist input
rather than duplicating firewall resources, adding parallel range-network
outputs, or hardcoding ports in runtime code.

## Gotchas

- Firewall priorities matter: explicit allow rules must have higher precedence
  than catch-all denies, and deny/allow ties should be avoided.
- VPC peering preserves source IPs; platform-to-range allows must match the
  actual GKE node/pod CIDRs or the specific provisioner source range, not a
  broad project or region range.
- GKE health checks, load balancer paths, private Google access, private
  service networking, Cloud SQL, Redis, Artifact Registry pulls, and control
  plane access have different trust boundaries. Do not collapse them into a
  single "platform internal" firewall rule without checking the destination and
  required direction.
- GCP implied deny ingress still exists. Adding explicit deny rules is useful
  for auditability and priority control, but it must not mask missing specific
  allows that the provisioner or GKE ingress requires.
- The AWS `check_tf_sg_cidrs` script does not inspect GCP firewall resources.
  Treat it as a policy pattern, not as validation coverage for this change.
- The range-network outputs are provider-neutral compatibility aliases used by
  the provisioner. Renaming or removing them turns a firewall fix into a
  runtime contract migration.

## Non-Goals

- Do not implement per-range VM firewall policy, NGFW policy, or Kubernetes
  NetworkPolicy changes as part of this platform VPC baseline unless the issue
  scope is expanded.
- Do not delete or mutate the project's default VPC/default firewall rules
  from `platform-core` unless Terraform first takes explicit ownership of that
  project-baseline surface.
- Do not add a new network inventory schema, provisioner DTO, exception
  hierarchy, or runtime config renderer for firewall metadata.
- Do not weaken Cloud Armor, GKE master authorized networks, IAP-only operator
  access, Workload Identity, Secret Manager, Terraform state, or Kubernetes
  default-deny NetworkPolicies while adding VPC firewall rules.
- Do not solve this by adding broad `allow internal` rules across peered VPCs;
  the range VPC is an isolation boundary, not another platform subnet.

## Validation

Run the repo-required checks for the touched surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
cd platform/terraform/gcp/environments/gcp-dev && terraform init -backend=false && terraform validate
```

If the implementation extends bootstrap validation, also run the targeted
bootstrap tests. If it changes workflows, run `actionlint`.

## Outcome — implementation landed 2026-05-11

This preflight was satisfied alongside #960, #962, and #963 in a grouped
security-hardening PR (branch
`959-high-no-firewall-rules-defined-on-gcp-vpcs`). Concrete artifacts:

- `platform/terraform/gcp/modules/platform-core/main.tf` — added
  `google_compute_firewall` resources covering range deny-by-default
  ingress, `range-allow-platform-provisioner` sourced from the
  dedicated provisioner pod CIDR (`var.gke_provisioner_pods_cidr`),
  optional range/platform direct break-glass admin SSH allows gated on
  `var.operator_admin_cidrs`, explicit platform-deny-external-SSH/RDP,
  and a tag-scoped platform allow-gke-health-checks rule. The optional
  admin-SSH allows ride at priority 800 — strictly higher precedence
  than the platform-deny-external-SSH/RDP rule at 900 so an explicit
  operator CIDR is not shadowed by the broader deny. These admin-SSH
  rules use direct source-CIDR matching at the VPC firewall layer and
  are intentionally NOT named "iap": IAP TCP forwarding presents
  traffic from Google's fixed `35.235.240.0/20` proxy range, and
  IAP-based access onto these VPCs is handled at the IAM / OS Login /
  bootstrap layer rather than via this firewall policy.
- **Per-pool pod-CIDR isolation for the provisioner.** The GKE subnet
  declares a third secondary range
  (`var.gke_provisioner_pods_secondary_range_name`, default
  `gke-provisioner-pods`, default CIDR `10.46.0.0/20`); the cluster's
  `ip_allocation_policy.additional_pod_ranges_config` declares it
  available; the provisioner node pool opts into it via
  `network_config.pod_range`. The range firewall rule now sources from
  this narrow CIDR rather than the broader `local.portal_network_cidrs`
  set — a compromised portal/worker/guacamole pod cannot reach range
  VMs on the admin ports.
- `platform/terraform/gcp/modules/platform-core/variables.tf` — added
  `range_provisioner_ports` and `operator_admin_cidrs` with the
  validation contracts described above (reject empty lists, reject
  `0.0.0.0/0` / `::/0`, reject out-of-range ports).
- `docs/adr/index.yaml` — ADR-008-R4 (added by preflight) remains the
  rule of record; ADR-008 evidence list now includes this preflight
  note.

Range-network outputs (`range_network_id`, `range_network_cidr`,
`range_network_region`, `portal_network_cidrs`) were intentionally
left unchanged — the firewall fix did not turn into a runtime contract
migration.
