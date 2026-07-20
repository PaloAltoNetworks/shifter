# GCP Range-Cell Boundary Controls Preflight

Issue: GitHub #1345, "Implement GCP firewall and identity isolation templates
for range cells."

This is requirement-free pre-implementation guidance. The GitHub issue title,
body, and acceptance criteria are the shipping contract. This note does not
implement the issue and is not an implementation plan.

## Decision Boundary

#1345 is the outer range-cell boundary for GCE-backed live-fire ranges. It
specializes ADR-030 and ADR-039; it does not create a new scenario topology
model, new range lifecycle, new access broker, or new public schema.

The platform owns deterministic cell identity, cloud resource ownership,
cross-range isolation, platform-network isolation, management ingress, external
IP posture, attached service-account posture, metadata/API hardening, and
rule-count discipline. Scenario realization remains responsible for internal
composition: host count, roles, containers, Windows/DC behavior, nested
Kubernetes, ports, DNS, bootstrap, and any narrower scenario-internal
connectivity.

## Authoritative Range-Cell Identity

The authoritative firewall targeting identity for the current implementation is
the deterministic per-range GCE network tag already produced by the GCE range
cell naming helpers:

- range target tag: `gcp_range_cell_naming._network_tag(range_id)`
- optional subnet/member tags: `gcp_range_cell_naming._subnet_tag(range_id,
  subnet_name)` when a rule truly needs a narrower target
- resource labels: `_range_labels(range_id, request_uuid)` for inventory,
  cleanup, and diagnostics only; labels are not an enforcement boundary
- service account: `GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL` is an IAM identity,
  not the cell firewall identity

This is a documented combination: network tags target firewall rules, labels
identify resources for cleanup/reconciliation, and service accounts limit cloud
API permissions. Do not introduce a second identity string or derive firewall
identity from scenario ids, usernames, role names, image profiles, or authored
subnet names except through the existing deterministic tag helpers.

Secure tags or firewall policies may be a future hardening seam if the
deployment needs IAM-governed tag binding or a lower rule count across many
VPCs. They must enter behind the same cell-identity helper/contract. Do not mix
legacy network tags and secure tags ad hoc in individual rule renderers.

## Architecture Decisions And Guardrails

- Generate boundary rules from cell identity and `network_bindings`, not from a
  platform-authored host/container/Windows/DC taxonomy.
- Keep rule count O(ranges), not O(hosts) and preferably not O(subnets). A
  shared-VPC deployment with 100+ concurrent ranges must not exceed GCP firewall
  quotas because every instance or authored internal service gets its own rule.
- Cross-range traffic must be denied by omission plus explicit egress posture:
  ingress allows source only from the same cell CIDRs and approved management
  sources; egress allows only same-cell CIDRs and explicitly approved endpoints
  before a catch-all deny.
- Platform-network reachability is not "internal". Range VMs must not egress to
  platform, pod, service, node, database, Redis, Secret Manager, GKE, GDC, or
  operator networks unless a named endpoint is intentionally approved.
- Management paths are ingress-only from the canonical portal/bastion/Guacamole
  source CIDRs to the approved remote-access ports. Do not add reciprocal range
  egress to platform CIDRs unless a separate endpoint contract requires it.
- Participant/range VMs stay private-only by default. The GCE instance resource
  must continue to omit external `access_config`; any explicit external-IP
  approval is a security exception with tests and documentation.
- Attached service accounts must be omitted when a guest does not need cloud
  APIs after creation. When a guest does need APIs, attach only the configured
  host service account with minimal IAM and keep participant-executable
  surfaces from reading its metadata token.
- Metadata/API abuse is controlled by making metadata credentials absent or
  low-value first, then adding guest/container blocks as defense in depth. GCE
  VPC firewall rules must not be claimed as the primary metadata-server
  control.
- Private Google Access and `GCP_RANGE_EGRESS_ALLOW_CIDRS` are explicit egress
  holes. They must stay coupled to config validators and tests; an empty
  allowlist must not imply an approved platform or internet path.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Closed range-cell contract | `shared.range_cells`, `tests/shared/test_range_cells.py` | Keep inputs/results closed, digest-bound, versioned, and free of secret values or scenario topology expansion. |
| GCE naming and identity | `gcp_range_cell_naming.py`, `tests/test_gcp_range_cell_naming.py` | Extend existing tag/name helpers instead of adding another identity grammar. |
| GCE plan and resource renderers | `gcp_range_cell_plan.py`, `gcp_range_cell_resources.py`, `tests/test_gcp_range_cell_resources.py`, `tests/test_gcp_range_cells.py` | Put boundary rules in the pure plan/resource layer and test rendered bodies without cloud calls. |
| Runtime config | `GCERangeCellConfig`, `load_gce_range_cell_config`, `scripts/gcp/render_runtime_env.py`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, runtime inventory, GKE Job admission env allowlists | New knobs must flow through the existing validated runtime-env path and admission allowlist. |
| Stable GCP VPC posture | `platform/terraform/gcp/modules/range/vpc`, `platform/terraform/gcp/modules/platform-core`, `docs/architecture/gcp-vpc-firewall-preflight.md`, ADR-008 | Keep stable VPC/PGA/DNS/routing assumptions in Terraform-owned surfaces; runtime rules must not contradict them. |
| IAM and secrets | `platform/terraform/gcp/modules/portal/iam`, ADR-008-R7, `gcp_guest_secrets`, `gcp_range_vertex_creds`, `shared.cloud.sensitive_env`, provisioner `log_redact` | Persist and output secret references only; do not widen project-level IAM to make metadata tokens useful. |
| Workflow and status | CMS/CTF range services, Engine launch intents, ADR-039 substrate boundary, `range_ops.py`, `range_terraform_runner.py` | Do not add a GCP-specific controller, status enum, lifecycle repository, or event family. |
| Errors and observability | `shared.cloud.exceptions`, `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact`, ADR-039 failure codes | Return bounded classified failures; log request/range/rule counts and sanitized fingerprints, not provider payloads or secret data. |
| Guardrails and validation | `scripts/adr_guard`, `.importlinter`, `.tflint.hcl`, GCP manifest tests, `scripts/check_tf_*` pattern | Add focused tests/checks for unsafe broad CIDRs/tags instead of relying on review memory. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: Mission Control and CTF continue through existing CMS/Engine
  range creation and ownership checks. No firewall, service-account, or access
  decision may trust request-body identity, scenario id, or client-selected
  backend data.
- Scenario shape: `RequestSpec` / `RangeSpec` or ACES realization validates the
  internal scenario artifact before it becomes a digest-bound range-cell
  request. Boundary rule generation consumes only `operation`, `network_bindings`,
  `access_declarations`, and deterministic cell identity.
- Range-cell parser: `shared.range_cells.validate_gcp_vm_range_cell_request`
  must reject unsupported versions, unknown fields, missing/duplicate network
  bindings, digest mismatch, and dangling access before Compute API mutation.
- Config validators: `load_gce_range_cell_config`, runtime inventory,
  `scripts/gcp/render_runtime_env.py`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`,
  and the GKE provisioner Job admission policy must admit every new env key
  deliberately and reject malformed CIDRs, ports, modes, project/image refs, and
  service-account inputs.
- Terraform and VPC policy: stable range VPC DNS/PGA/routing and platform VPC
  rules remain Terraform-owned. Runtime firewall templates must align with
  `platform/terraform/gcp/modules/range/vpc` and `platform-core` outputs rather
  than inventing a parallel network inventory.
- Compute API resource shape: `gcp_range_cell_resources` must continue to render
  proto-plus field names, private-only NICs, Shielded VM settings, internal
  addresses, block-project-SSH metadata, target tags, and service-account
  blocks deterministically.
- Metadata/API surface: no secret value or broadly useful cloud credential may
  appear in instance metadata, startup scripts, Terraform output, DB JSON,
  events, logs, or process argv. Metadata-token exposure must be made harmless
  through no service account or minimal IAM; container/guest metadata blocks are
  defense in depth and must be tested for supported compositions.
- OS/process exposure: provisioner commands remain structured argv
  (`range <operation> --request-id <uuid>`). Do not pass scenario artifacts,
  private keys, service-account JSON, startup script bodies, or provider
  payloads through shell strings, workflow output, or process titles.
- Error envelope and events: Compute/IAM/firewall failures map to ADR-039
  classified failures and existing sanitized API/event envelopes. Raw provider
  errors, full inventories, metadata responses, and secret references/values do
  not enter user-visible messages.

## Extensibility Seam

The seam is a small boundary-policy shape inside the GCE range-cell config/plan,
not a public scenario schema:

- cell identity strategy: network tag now, secure tag/firewall policy later
- approved management sources and ports
- approved egress endpoints: same-cell CIDRs, Private Google Access VIP,
  operator-declared allowlist, or future named endpoint groups
- service-account attachment policy by guest/profile capability
- metadata-token containment policy by guest/profile capability
- network mode: shared VPC now, VPC-per-range when reachability and quotas allow

The obvious next variation is replacing per-range network-tag firewall rules
with secure tags or a higher-level firewall policy. That should require editing
the identity strategy and renderer, not CMS, CTF, public schemas, access
brokers, or scenario realizers.

## Gotchas And Anti-Patterns

- Do not use a broad `allow internal`, `source_ranges = [range_network_cidr]`,
  `destination_ranges = [range_network_cidr]`, or `0.0.0.0/0` allow as a
  shortcut. In a shared VPC, those are cross-range escape paths.
- Do not let `PORTAL_NETWORK_CIDRS` become an all-purpose platform allowlist.
  It is a management-source contract, not permission for range VMs to call back
  into platform services.
- Do not attach the host service account to every VM merely because the config
  has one. A participant-executable VM with no post-create API need should have
  no attached service account.
- Do not rely on `block-project-ssh-keys`, `enable-oslogin=false`, or guest
  iptables as substitutes for least-privilege IAM and no external IP.
- Do not store service-account keys, SSH private keys, RDP passwords, generated
  startup scripts with secrets, metadata tokens, or provider responses in
  state, events, Terraform outputs, test snapshots, or logs.
- Do not treat the scenario `connected_to` graph as the platform boundary
  contract. It can inform legacy compatibility, but the outer boundary must
  preserve scenario-authorized intra-cell communication without standardizing
  scenario internals.
- Do not create per-range service accounts, secure tags, firewall policies, or
  VPCs as a hidden side effect without quota/cost/cleanup tests and a clear
  ownership model.
- Do not add a duplicate schema, validation package, exception hierarchy,
  workflow branch, access service, or repository for boundary controls.

## Non-Goals And Boundaries

- No implementation in this preflight note.
- No formal Ground Control requirement.
- No scenario-internal topology standardization, no universal host/container/DC
  taxonomy, and no new public range DSL.
- No redesign of GDC, GKE, Kubernetes Job admission, Identity Platform,
  Guacamole, Cloud Armor, AWS range isolation, or NGFW policy.
- No external IP support except as an explicit future exception.
- No claim that shared-VPC plus firewall is stronger than VPC-per-range. The
  shared-VPC posture is acceptable only when the boundary rules and validation
  pass; VPC-per-range remains the stronger isolation option when quota, cost,
  and provisioner reachability are solved.

## Validation Surface

Future implementation evidence should include focused tests for deterministic
rule generation, rule-count bounds for 100+ ranges, cross-range private-IP
denial, platform CIDR/pod/service/node denial, no external IPs, no broad
CIDR/tag regressions, service-account omission/minimality, metadata-token
uselessness from participant surfaces, and approved management/PGA/egress
exceptions only.

Touched architecture, Terraform, workflow, Kubernetes, or `shifter_platform`
surfaces must still pass the repo-required ADR guard and stack-native checks for
the files changed.
