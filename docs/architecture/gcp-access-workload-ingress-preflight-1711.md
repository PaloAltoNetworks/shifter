# GCP Access-Workload Ingress Preflight (#1711)

Issue: GitHub #1711, "Dedicated access-workload identity + cell-targeted
range ingress (GCP range access hardening)."

This is requirement-free pre-implementation guidance. The GitHub issue is the
shipping contract. This note does not implement the issue and is not an
implementation plan.

## Decision Boundary

#1711 hardens the private network path delivered by #1349. It does not create a
new participant authorization model, access broker, range-cell identity,
protocol schema, secret flow, or lifecycle controller.

The new identity is specifically a **network-source identity**: portal and
`guacd` pods receive addresses from a dedicated VPC-native GKE pod secondary
range, and only that range is admitted to per-cell SSH/RDP ingress. It is not a
Kubernetes service account, GCP service account, Workload Identity principal,
node IP, pod label, or user identity. Those existing identities retain their
current IAM and RBAC purposes.

## Architecture Decisions And Guardrails

- Mirror the existing provisioner secondary-range/node-pool pattern in
  `platform/terraform/gcp/modules/portal/vpc` and `portal/gke`. The access pod
  CIDR, secondary-range name, node-pool size, and machine type remain
  environment-owned Terraform inputs; do not hardcode deployment CIDRs in
  Python or Kubernetes templates.
- Make the access pool exclusive. The pool needs a dedicated node label and a
  `NoSchedule` taint; portal and `guacd` need matching required placement and
  the narrow toleration. A preferred affinity or node selector alone does not
  make a firewall source range mean "only access workloads", because unrelated
  unspecialized pods may otherwise schedule onto that pool.
- Preserve the existing portal and `guacd` pod labels used by the default-deny
  NetworkPolicy. Placement and NetworkPolicy are two independent gates:
  placement gives the GCE firewall a source identity, while NetworkPolicy
  limits which pods may use that route. Neither substitutes for the other.
- Keep `guacamole-client` off the access pool. It serves HTTP and JSON auth;
  `guacd` is the SSH/RDP dialer. Keep background workers off the pool even
  though they use the same platform image as the portal ASGI deployment.
- Add the dedicated access CIDR to the cluster's
  `additional_pod_ranges_config`, the GKE subnet secondary ranges, the access
  node pool's `network_config.pod_range`, and a non-secret Terraform output.
  Validate it as canonical IPv4 CIDR and disjoint from node, default-pod,
  provisioner-pod, service, control-plane, private-service, and range-network
  CIDRs. Provider rejection is a backstop, not the first validation layer.
- `ACCESS_NETWORK_CIDRS` is the provisioner-facing projection of that Terraform
  output. It passes through the existing GCP runtime renderer, installation
  runtime inventory and published bundle projection, Engine provisioner-env
  forwarding, sensitive-env classification, and fail-closed GKE Job admission
  allowlist. It is public configuration and belongs in the runtime ConfigMap,
  not Secret Manager or a per-Job Secret.
- Keep `GCERangeCellConfig` and `gcp_range_cell_firewall.build_firewall_plan` as
  the only GCE runtime firewall config/plan contract. The existing
  `access_network_cidrs` field and `_validated_boundary_cidrs` validator are the
  canonical incumbents; do not add another DTO, parser, or firewall planner.
- Remove the security fallback that combines participant ports with a broad
  portal/management source when the access CIDR is empty. Missing access CIDRs
  must omit participant ingress or fail before mutation. Management ingress
  may still render from its configured management source, but it must never
  inherit RDP or participant SSH as a fallback.
- For this issue, retain `PORTAL_NETWORK_CIDRS` / `portal_network_cidrs` only as
  the published compatibility name for the management-source input and narrow
  its GCP Terraform producer to the actual provisioner/management pod range.
  Do not keep the whole node/default-pod ranges in it and do not introduce a
  second synonymous management field. A future public rename requires an
  installation-contract migration rather than an undocumented alias tree.
- Render two deterministic, bounded per-cell rules through the existing naming
  and resource layers: participant access from `access_network_cidrs` on TCP
  22/3389, and host management from the provisioner/management source on TCP 22
  plus the configured host-management SSH port. Both target the existing
  `_network_tag(range_id)`; role, OS, scenario id, address, and credential
  presence never determine firewall identity.
- Treat the existing Terraform range-VPC provisioner rule as the stable
  management baseline. Do not widen it for access workloads and do not collapse
  it with the per-cell participant rule. GCP firewall allows are additive, so
  effective semantics must be tested across stable Terraform rules and dynamic
  per-cell rules, not one file at a time.
- Existing firewall names are not converged today:
  `gcp_range_cells._ensure_firewall` returns as soon as a rule exists. Therefore
  a new narrow `*-access` rule plus a newly rendered `*-mgmt` body would leave
  an old broad `*-mgmt` rule live. The canonical ensure function shared by the
  legacy and RAES GCE paths must reconcile the security-relevant body (or fail
  closed), and rollout evidence must cover already-active cells. Do not create
  a second migration-only firewall controller.
- Preserve O(ranges), not O(instances), rule growth and convergent teardown.
  Added/renamed rules must be deleted for legacy and RAES ranges, including
  partially created and repeated-destroy cases.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| GKE address identity | `platform/terraform/gcp/modules/portal/vpc/main.tf`, `portal/gke/main.tf`, `gke_provisioner_pods_cidr`, provisioner node pool `network_config.pod_range` | Add a sibling access secondary range and pool; retain VPC-native alias-IP and private-node posture. |
| Terraform composition | `platform-core` variables/locals/module calls/outputs and `gcp-dev` environment root | Carry one environment-owned CIDR/range-name/pool shape through the existing module boundary; no parallel network inventory. |
| Runtime env contract | `scripts/gcp/render_runtime_env.py`, `installation.runtime_inventory`, `installation.registry`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, GKE Job admission manifests/tests | Project and forward the non-secret access CIDR through every existing shape gate. |
| Workload rendering | Helm `values.yaml`/schema/GCP profiles and portal/`guacd` deployment templates; `platform/k8s/gcp/base` plus overlay rendering | Use required placement and keep Helm/Kustomize semantics equivalent; preserve current pod labels, service accounts, security contexts, probes, resources, and anti-affinity. |
| Kubernetes network policy | Helm and Kustomize `allow-platform-range-access-egress`, bootstrap and GCP NetworkPolicy renderers | Keep portal + `guacd` as the only dialers and TCP 22/3389 as the fixed destination policy. |
| GCE config and planning | `config._gce.GCERangeCellConfig`, `load_gce_range_cell_config`, `gcp_range_cell_firewall.build_firewall_plan`, `gcp_range_cell_naming` | Reuse the existing field, CIDR validation, fixed rule model, and per-range tag/name identity. |
| Provider realization | `gcp_range_cell_resources.firewall_resource`, `gcp_range_cells._ensure_firewall`, `raes_gcp_apply`, `gcp_range_cell_destroy` | Preserve proto-plus field translation, reconcile existing rules, and share apply/destroy behavior across both GCE plan producers. |
| Access authorization | `shared.range_cells`, Engine terminal service, Mission Control Guacamole builders, CTF/Mission Control ownership and READY checks | Network admission remains defense in depth; current owner/member/channel checks still run before enqueue and dial. |
| Errors and logs | Terraform/bootstrap validation, `shared.cloud.exceptions`, `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact` | Use existing failure paths and sanitized fingerprints; no infrastructure-specific exception hierarchy or raw provider payload in API/events/logs. |
| Tests and guards | provisioner config/plan/resource/apply/destroy tests, bootstrap/runtime-inventory tests, chart contract hashes/tests, Kustomize parity/admission tests, ADR guard and stack-native validators | Assert effective allow semantics and negative broad-CIDR cases, not merely presence of new strings. |

## Cross-Cutting Layers The Design Must Pass

- **Authentication and authorization:** session/API-token authentication,
  participant ownership/active state, range READY state, member binding, and
  declared `ssh`/`rdp` channel remain authoritative before enqueue and again
  before dial. A pod CIDR grants route eligibility only; it grants no user or
  target authorization.
- **Terraform shape:** environment variables feed `platform-core`, portal VPC,
  GKE cluster additional ranges, and the access pool from one source. CIDR
  syntax, non-universal scope, and cross-range non-overlap fail before apply.
  Private nodes, Cloud NAT, Workload Identity, Binary Authorization, Shielded
  VM posture, and the common node service account remain unchanged.
- **Helm/Kustomize shape:** the Helm values schema must admit only the bounded
  placement fields it renders, and GCP profiles supply them; AWS/neutral
  profiles must not acquire a GCP node label. Static GCP manifests and the
  bootstrap-generated Helm path must render equivalent required placement and
  preserve the current access NetworkPolicy selector.
- **Runtime/env binding:** Terraform output becomes `ACCESS_NETWORK_CIDRS` in
  the generated ConfigMap, installation inventory/publication, Engine forwarding
  tuple, task-runner literal-env split, and both admission-policy copies. The
  admission test comparing its allowlists to `_GCP_PROVISIONER_ENV_KEYS` must
  remain the drift oracle.
- **Provisioner config and firewall shape:** `_parse_csv_env` parses the value;
  `_validated_boundary_cidrs` canonicalizes/deduplicates IPv4 and rejects `/0`;
  cross-field validation rejects overlap with management sources. The pure plan
  emits explicit sources, fixed ports, and the deterministic cell tag before
  `firewall_resource` translates to Compute proto field names.
- **Realized cloud state:** `_ensure_firewall` must compare/reconcile an existing
  rule rather than equating name existence with correctness. Apply, RAES apply,
  destroy, partial failure, and repeated destroy all use the same ownership and
  operation-wait conventions.
- **Secret surface:** CIDRs, labels, taints, and ports are non-secret. Keep them
  out of Secret Manager/per-Job Secrets so secret classification stays truthful.
  Do not change portal, `guacd`, node, or provisioner IAM to implement a network
  source identity; existing credential references and just-in-time resolution
  remain untouched.
- **OS/process exposure:** no credential or topology blob is added to process
  argv, shell strings, GCE metadata, startup scripts, workflow output, or Helm
  release secrets. The non-secret CIDR may ride Terraform plans and ConfigMap
  env; provisioner commands remain the current structured operation argv.
- **Errors and observability:** malformed/missing topology fails in Terraform or
  bootstrap/config validation, while provider failures use existing bounded
  provisioner/cloud error handling. Do not expose raw Compute responses or
  private inventories in user error envelopes. Existing Terraform diffs,
  subnetwork flow logs, sanitized rule-name fingerprints, and focused rendered
  semantics are the evidence surfaces; do not add application logs as a second
  source of firewall truth.
- **Persistence and workflows:** no database schema, repository, event, status,
  or controller changes are needed. The bootstrap-owned Helm renderer and the
  existing GCP deployment workflow remain the only deployment projections.

## Extensibility Seam

The infrastructure seam is the environment-owned access-pool tuple: pod CIDR,
secondary-range name, node label/taint, pool size, and machine type. The
workload seam is an explicit list of trusted dialers rendered into required
placement and NetworkPolicy selectors. Adding a future dialer requires an
intentional update to both gates; broad label wildcards are prohibited.

The protocol seam remains the closed logical channel vocabulary in
`shared.range_cells` and its fixed channel-to-port projection. The existing
Helm `rangeAccessPorts` value is renderer-owned plumbing, not an
operator-selectable arbitrary-port escape hatch. A future protocol must extend
the closed channel contract, broker, GCE ingress, and NetworkPolicy together;
it must not be enabled by adding a number to one values file.

## Gotchas And Anti-Patterns

- Do not call a KSA, GCP service account, pod label, node tag, or IAM binding the
  GCE source identity. The firewall observes the routed pod address.
- Do not use preferred affinity. Do not add a selector without making the pool
  exclusive, and do not replace existing pod anti-affinity with source-identity
  placement; they solve different problems.
- Do not schedule `guacamole-client`, Celery workers, the provisioner launcher,
  or provisioner Jobs on the access pool.
- Do not fall back from missing access CIDRs to node/default-pod/portal CIDRs,
  `0.0.0.0/0`, or the provisioner CIDR. Loss of participant connectivity is the
  safe failure mode.
- Do not keep RDP on the per-cell management rule, union access and management
  sources, or rely on peering as authorization.
- Do not only test the newly rendered plan. Name-only create-or-observe leaves
  broad deployed rules unchanged; effective-state reconciliation is part of
  the security boundary.
- Do not create per-workload firewall rules or node pools per range. The access
  pool is environment-scoped; GCE ingress stays cell-targeted and O(ranges).
- Do not duplicate CIDR schemas, validation functions, firewall plan/resource
  types, exception classes, runtime renderers, Helm charts, lifecycle paths, or
  access authorization logic.
- Do not weaken the existing default-deny NetworkPolicy, GCE range deny,
  provisioner source isolation, no-external-IP posture, Workload Identity,
  admission policy, or secret handling to make placement work.

## Non-Goals And Boundaries

- No issue implementation in this preflight.
- No formal Ground Control requirement; issue #1711 is authoritative.
- No change to AWS security groups, GDC networking, user-facing access APIs,
  browser SSH/Guacamole behavior, participant authorization, credential
  persistence, or session revocation.
- No new GCP IAM identity or permission, bastion, IAP participant role, public
  IP, NAT ingress, service mesh, proxy, or per-session firewall mutation.
- No general node-pool framework or arbitrary workload-placement DSL. Reuse the
  chart's workload schemas with one bounded placement shape where needed.
- No firewall logging mandate. Enable provider firewall logging separately only
  with an explicit evidence/operations requirement and cost/retention policy.

## Required Evidence

- Terraform validation and focused tests prove one disjoint access secondary
  range, one private access pool, and exclusive required placement.
- Rendered Helm GCP profiles and Kustomize manifests put exactly portal and
  `guacd` on the access pool; AWS/neutral profiles do not; the existing
  NetworkPolicy remains limited to those components and TCP 22/3389.
- Runtime-renderer, installation-publication, task-env, and admission parity
  tests prove `ACCESS_NETWORK_CIDRS` reaches provisioner Jobs as a non-secret
  literal and cannot be overridden.
- Pure plan and Compute-resource tests prove participant and management rules
  have disjoint sources/ports, explicit per-cell tags, no universal/broad
  source, deterministic names, and bounded rule counts for 100+ cells.
- Apply tests start with an existing legacy broad `*-mgmt` rule and prove it is
  narrowed or the operation fails closed; active-cell rollout evidence proves
  old broad rules are not left behind. Destroy tests cover both rule names and
  partial/repeated cleanup for legacy and RAES paths.
- Touched architecture, Terraform, Kubernetes, workflow, and
  `shifter_platform` surfaces pass the repository ADR guard and their required
  stack-native validators.
