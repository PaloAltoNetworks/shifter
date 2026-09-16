# GCP Range-Cell Zone-Pool Preflight

Issue: GitHub #2029, "backport(gcp): multi-region zone pool for GCP range
cells (`RANGE_NETWORK_ZONES`) from `gcp-dev` to `dev`."

This requirement-free note records the architecture boundary for the backport.
It does not implement the issue and is not an implementation plan.

## Implementation decisions (supersede two non-goals below)

Pre-push review surfaced two correctness holes that documentation alone could not
close, so two boundaries this note originally set as non-goals were deliberately
reversed for #2029 (authorized during implementation):

1. **Realized placement is chosen at creation and persisted.** The zone is selected
   from the `RANGE_NETWORK_ZONES` pool **once, in the range-create transaction**
   (alongside `subnet_index`, platform side: `engine.services._range_placement`) and
   stored on `mission_control_range.placement_zone` (`engine.Range`, migration
   `0054`). The provisioner is a pure reader (`engine/provisioner/range_placement.py`):
   both legacy and RAES apply/destroy bind the config to the stored zone and never
   recompute from the pool. Deciding at creation makes placement a durable property
   of the range from birth, so: teardown is correct even if the pool is later
   reordered/resized; there is no apply-time race (creation is single and
   transactional); and an empty `placement_zone` unambiguously means a pre-#2029 /
   single-zone range (never reinterpreted through the current pool). This reverses
   the "no new placement table/column" non-goal.
2. **Per-region range NAT is delivered.** `platform/terraform/gcp/modules/range/vpc`
   provisions a Cloud Router + external address + Cloud NAT for every non-primary
   region a pooled zone lives in (empty keeps single-region behaviour, and the
   primary region's existing NAT is untouched). A cross-region cell therefore has a
   real egress path rather than only a private/PGA-only one. This reverses the "no
   public internet-egress expansion without a separately reviewed regional NAT
   design" non-goal. NAT regions are **derived from the zone pool itself**: the
   module takes the `range_network_zones` list (the same operator input as the
   runtime `RANGE_NETWORK_ZONES`) and derives each zone's region, so NAT coverage
   cannot diverge from where cells are actually placed.

## Decision Boundary

`RANGE_NETWORK_ZONES` is an ordered, deployment-owned placement policy for
GCE range cells. It is not scenario intent, a range-cell request field, a new
network schema, or a second region setting. `GCERangeCellConfig` continues to
describe one realized cell with exactly one mutually consistent `zone` and
`region`; the placement helper derives that per-cell config from the existing
persisted range allocation slot before plan rendering or cloud-client creation.

The scalar `RANGE_NETWORK_ZONE` remains the required compatibility placement
and the fallback for an unset/empty pool or a caller without a slot. Pool
entries are fully qualified GCE zones. Parse them with the incumbent
`config._env._parse_csv_env`, validate their shape at the provisioner config
boundary, reject duplicates rather than silently creating weighted placement,
preserve declared order, and derive the region from the selected zone. Invalid
configuration must fail with the existing authored `RuntimeError` convention
before any provider or secret mutation; do not add an exception hierarchy.

Selection is `zones[slot % len(zones)]`, where `slot` is the existing zero-based
allocation slot (`mission_control_range.subnet_index - 1`), not a range id,
request hash, scenario field, or newly persisted placement record. Apply,
failed-apply cleanup, and destroy must all render from the same selected config.

## Lifecycle Invariant

The no-new-state design is correct only while the ordered pool is unchanged for
the lifetime of every active range. Reordering, adding, removing, replacing, or
deduplicating an entry changes `slot % len(zones)` and can make reconstructive
destroy look in the wrong region/zone, stranding resources.

Treat the exact ordered pool as drain-before-change configuration. A deployment
must not mutate it while any range placed by that pool is non-terminal. If the
product needs live pool changes, rebalancing, or independent per-region
capacity weights, the design must change to persist the chosen placement or a
versioned placement policy; the modulo rule must not be presented as stable
across pool revisions.

## Canonical Incumbents

| Concern | Canonical incumbent and required reuse |
| --- | --- |
| Placement input | `config._env._parse_csv_env`, `config._gce.GCERangeCellConfig`, and `load_gce_range_cell_config`; keep parsing and fail-fast config validation here rather than in plans, resources, or controllers. |
| Stable slot | `Range.allocate_subnet_index` and `provisioner_db.get_range_data_by_request_id`; use the persisted 1-based subnet index and convert once to the existing zero-based pool slot. |
| Lifecycle | `gcp_range_cells.apply_range_cell`, `gcp_range_cell_destroy.destroy_range_cell`, `render_range_cell_plan`, and existing compensation; bind before any plan/client mutation and keep apply/destroy symmetric. |
| Runtime rendering | `.github/workflows/_gcp-dev.yml`, `scripts/gcp/render_runtime_env.py`, `installation.runtime_inventory_gcp`, and the generated GCP backend-bundle output contract; the workflow must explicitly project the repository/environment variable and the current published artifact must be regenerated, never hand-edited. |
| Job dispatch | `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, `shared.cloud.sensitive_env`, the provider-neutral Kubernetes task runner, and the `platform-runtime` ConfigMap; the zone list is non-secret literal configuration and empty values remain omitted. |
| Admission | Both `restrict-provisioner-jobs` manifests, `test_gcp_job_launcher_manifests.py`, and the Helm render hashes; admission must continue requiring exact equality with ConfigMap data, and the base and Helm policies must remain equivalent. |
| Network | The global range VPC, network-wide firewall rules, per-cell regional subnets, and `platform/terraform/gcp/modules/range/vpc`; do not duplicate VPCs, peerings, routes, or firewall stacks in the provisioner. |
| Errors and logs | Existing provisioner `RuntimeError` configuration failures, lifecycle error mapping, ECS logging, and `log_redact`; use bounded authored diagnostics and log only non-secret placement fields needed for correlation, not the raw pool. |

The source commits predate the current `runtime_inventory_gcp` parity and
published-contract gates. Port the behavior into these current incumbents; do
not paste stale allowlists or source-branch Helm digests.

## Cross-Cutting Security And Runtime Layers

- **Authorization:** Mission Control, CTF/CMS, Engine ownership, persisted
  backend/purpose, and request-generation checks stay unchanged. A client or
  scenario cannot choose a zone or pool.
- **Workflow/config source:** `vars.RANGE_NETWORK_ZONES` is non-secret operator
  configuration. The canonical GCP workflow must pass it to the renderer; it
  must not be inferred from a branch, scenario, range id, or control-plane
  region.
- **Renderer and inventory shape:** the optional key must appear in the GCP
  renderer inventory, provisioner forwarded-role inventory, renderer tests,
  and regenerated current backend-bundle contract. The checked-in generated
  env stub remains comment-only.
- **ConfigMap and Job shape:** the portal/launcher reads the value from
  `platform-runtime`; `_GCP_PROVISIONER_ENV_KEYS` forwards it; `split_env`
  classifies it as plain; the Job carries it as literal env; admission permits
  it only when name and value exactly match the ConfigMap. It does not belong in
  the per-Job Secret.
- **OS exposure:** zones may appear in the Kubernetes Job spec, ConfigMap,
  audit records, and process environment because they are non-secret. They must
  not move into command arguments, queue payloads, shell strings, or secret
  stores.
- **Provisioner config validation:** CSV normalization, duplicate/shape checks,
  slot selection, and zone-to-region derivation complete before plan rendering
  or client construction. Provider SDK errors are not the zone validator.
- **Persistence and replay:** `subnet_index` remains the sole placement input.
  Do not add a zone column, output bag, alternate repository, or destroy-only
  lookup while the ordered-pool invariant is accepted.
- **Error envelopes:** configuration errors use a bounded authored message that
  names the setting and entry position without dumping the whole environment.
  Existing lifecycle wrappers remain responsible for status/error projection;
  no raw provider response or environment snapshot crosses that boundary.
- **Observability:** record the selected slot, zone, and derived region at the
  existing lifecycle correlation point. Do not log the full pool, environment,
  provider objects, or credentials, and do not create zone-valued unbounded
  metrics without an established metric contract.

## Network Gotcha

The shared range VPC and its firewall rules are global, so cross-region subnets
need no new peering or duplicate firewall rules. The existing range Cloud
Router, external address, and Cloud NAT are nevertheless bound to one
`var.region`. A cell in another region is therefore not covered by that NAT.
Private Google Access continues through the global private API DNS/route plus
the per-subnet flag, but a profile with `allow_public_web_egress=true` cannot
claim its documented public TCP 80/443 path outside the NAT region.

This backport must not silently claim cross-region public-egress parity. Either
the accepted workload is explicitly private/PGA-only, or the issue boundary
must expand to a reviewed per-region NAT design and Terraform validation. A
provisioner firewall allow alone is not an egress path.

## Extensibility Seam

The seam is the pure transformation from `(single-cell config, stable slot,
ordered zone pool)` to a single-cell config. Downstream GCE plan/resource code
continues to consume one zone and one region and therefore does not change when
another placement policy is introduced. A future RAES placement integration
must supply its persisted allocation slot to this same seam on both apply and
destroy; it must not copy the modulo expression.

The named source commits wire the legacy `gcp_range_cells` lifecycle only.
`raes_gcp_apply` / `raes_gcp_destroy` are separate current GCE lifecycle paths
and also consume `GCERangeCellConfig`; they are not implicitly covered. Delivery
evidence must state that boundary. If #2029 is intended to cover the current
RAES hard-cutover path, both RAES lifecycle sides need the same stable-slot
binding before the issue can be considered complete.

## Gotchas And Anti-Patterns

- Do not read `RANGE_NETWORK_ZONES` independently in apply and destroy modules;
  keep one parser/selector and pass the realized config onward.
- Do not sort or silently deduplicate the pool; either operation changes slot
  mapping. Reject duplicates with an authored config error.
- Do not allow the pool to replace `RANGE_NETWORK_ZONE`; the scalar is the safe
  fallback for missing-slot callers and unset pools.
- Do not derive region from `RANGE_NETWORK_REGION` after selecting a pooled
  zone, and do not let zone and region disagree in a plan.
- Do not use range id, request UUID, Python hashing, database row order, or
  current fleet size for placement.
- Do not update only the Helm admission template. The static GCP base, direct
  allowlist/forwarding parity test, and both GCP render hashes must move
  together.
- Do not update the renderer without the current installation inventories and
  generated published contract, or the backend contract will lie about which
  process receives the key.
- Do not assume a GitHub `vars.*` value reaches a step automatically; the
  reusable GCP workflow requires explicit projection.
- Do not copy the event-only `gcp-dev` replica/node/database tuning from
  `b0fd501d2`.

## Non-Goals

- No `gcp-dev` capacity tuning, Terraform quota changes, or tenant-specific
  values/tfvars backport.
- No new controller, service, DTO, public scenario field, lifecycle status, event
  family, or exception hierarchy. (The one persisted `placement_zone` column is
  the deliberate exception per "Implementation decisions" above.)
- No VPC, peering, IAM, secret, guest-image, or machine-type policy change.
  (Per-region Cloud Router/NAT is the deliberate exception per "Implementation
  decisions" above.)
- No dynamic rebalancing or migration of already running cells; persisted
  placement pins a cell to its original zone, it does not move it.
- No claim that the legacy lifecycle change automatically covers RAES (it is
  covered explicitly and symmetrically).
