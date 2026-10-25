# RAES GCE shared-VPC subnet allocation: architecture preflight #2219

Issue #2219 is the authoritative contract; no Ground Control requirement is
attached. This note is design guidance, not an implementation plan or evidence
that the behavior is implemented. Inspection baseline:
`d6ca9faea7dd55a7cfa99a377aa31ef5402c9d7d`.

## Decision and boundaries

RAES-native GCE ranges in `shared-vpc` mode must use the existing Engine-owned
subnet coordination boundary for every network that becomes a GCE subnetwork,
including fixed-CIDR authored networks and the existing backend-default network.
One operation-generation-fenced reservation batch owns the complete ordered
network shape for a range. `vpc-per-range` behavior is outside this fix.

The authored RAES ProvisioningPlan remains immutable intent. A process-local,
copied realization pairs each stable RAES network address with its reserved CIDR;
it does not rewrite `mission_control_range.range_config`, add a Shifter transport
schema, or publish allocation state in RAES completion evidence. The existing
`GceNetworkAllocation` / `RaesGcePlanOptions` adapter seam should carry this
ordered projection instead of the current scalar `allocated_network_cidr`.

Every downstream GCE consumer must read the same realized projection:

- `RangeCellPlan` subnets and instance network interfaces;
- deterministic private-IP assignment;
- ACL endpoint lookup, service-source CIDRs, base firewalls, router/NAT subnet
  membership, and the static cross-range leak suite;
- provision, warm activation, destroy, and independent cleanup inventory.

Changing only `SubnetPlan.cidr` is unsafe: ACL lookup currently reads
`RaesPlan.networks` and would retain the authored CIDR. Firewalls must stay
range-scoped to realized subnets; neither the tenant supernet nor a peer range may
become an allow source or destination.

The stable reservation identity is the canonical RAES resource address, in the
same deterministic order used by `parse_plan`; display names are not identities.
The existing synthetic address `backend.gce.network.default` remains the identity
for open selection. A retry with changed identities, order, network, supernet, or
prefix is a conflict under the existing reservation fingerprint, not a second
allocation attempt.

## Prefix and address semantics

The current coordination contract accepts one prefix length for an entire batch
and only `/24` or `/28`. It cannot atomically reserve a mixed-prefix batch. The
legacy `_reserve_range_subnet_cidrs` helper hard-codes `/28`, so calling it
unchanged is not correct for RAES: `smoke-linux` is authored as `/24` and uses a
static host offset beyond a `/28`.

The implementation must derive an explicit supported reservation shape before
cloud mutation. Homogeneous authored `/24` or `/28` networks fit contract v1.
Backend-open networks in the same batch may adopt that batch's prefix because
they carry no authored size. A genuinely mixed fixed-prefix plan, or a prefix
outside the accepted set, must fail closed unless the versioned shared contract
and Engine routine are deliberately evolved to accept ordered per-network
prefixes atomically. Multiple v1 reserve calls for one request are prohibited:
they conflict with retry identity and can create partial ownership.

Static addresses are authored network-relative intent. Parse them from the
pinned RAES 3.5 payload into the existing process-local `RaesPlanNode` projection,
using the same strict-accessor and producer/consumer parity pattern as other RAES
fields. Do not add them to the serialized transport envelope. For each address,
preserve the host offset from the authored network and apply it to the reserved
network. Gateway-like network-relative values must be treated consistently even
when GCE supplies the gateway implicitly.

Validation must happen before provider or secret clients are constructed:

- both authored and realized networks and addresses are canonical IPv4;
- the address belongs to the referenced authored network and its rebased address
  belongs to the reserved network;
- network handles resolve unambiguously and assignments are unique per subnet;
- the realized address is in the existing GCE assignable-host set; and
- unspecified addresses use the existing deterministic assignment order while
  skipping explicitly claimed addresses.

Do not invent semantics for an ambiguous `count`/properties shape. Match the
pinned RAES producer/reference-backend meaning and fail closed when a payload
cannot be mapped one-to-one. Producer admission and the standalone provisioner
parser both need the check: the latter is the replay/version-skew backstop, and
`tests/shared/raes/test_plan_provisioner_parity.py` keeps the two interpretations
aligned rather than sharing an impermissible producer import.

## Ownership, failure, and teardown

`shared.subnet_coordination`, the SECURITY DEFINER routines from migration 0046,
and `SubnetAllocation` remain the only allocation policy and persistence
authority. Reservation is synchronous pre-mutation coordination, fenced by the
current operation and request UUID. The provisioner retains only EXECUTE on the
fixed reserve/read/release routines; it receives no direct allocation-table
grant. Provider observations remain drift evidence, not range-owned rows.

Capacity release follows ownership proof, not control-flow completion:

- A failure before any provider mutation may release its reservation directly.
- Once provider mutation can have begun, compensation must use the canonical
  destroy path and independent inventory. Release is allowed only after
  `VERIFIED_ABSENT` for the complete owned-resource scope.
- `RESIDUALS_FOUND`, `INCOMPLETE`, a failed delete, or a failed inventory retains
  the reservation for retry and operator recovery.
- Normal destroy reconstructs the same network-to-CIDR projection from persisted
  reservation rows, uses it for both deletion and inventory, and releases only
  after absence is proved.

The current RAES destroy order releases the scalar allocation before inventory;
that order is incompatible with ADR-063-R4/R5 and must not be copied for the
generalized path. Likewise, the legacy destroy helper's fallback from a missing
reservation to authored CIDRs is not safe for RAES fixed networks. A missing
required realization may use a narrow names-only cleanup/inventory projection
where the provider API permits it, but must never cause provider reconciliation
against the authored CIDR or claim verified release without absence evidence.

The realization projection must remain available to warm activation and retained
for old-generation teardown. It is allocation state, not a public result field,
secret, sidecar, or completion-evidence term.

## Cross-cutting boundaries that remain authoritative

| Boundary | Required passage |
| --- | --- |
| RAES admission and transport: `shared/raes/runtime_target.py`, `_runtime_target_envelope.py`, `network_family.py`, `operation_input.py` | Preserve exact RAES serialization, capability/topology diagnostics, IPv4-only admission, bounded immutable operation input, and the exact producer-version pin. Static-property diagnostics and provisioner parsing must agree through parity tests. |
| Operation authority: `raes_range_ops.py`, `shared.range_instantiation_policy`, `provisioner_db_operation_input.py` | Keep backend/purpose admission, request ownership, immutable input, and current operation generation. Network ID, tenant supernet, prefix policy, and provider placement are server-owned; authors do not select them. |
| Reservation contract: `shared/subnet_coordination.py`, `components/network/_allocate.py`, migration 0046, `engine/services/_subnet_coordination.py` | Reuse UUID, CIDR, count, prefix, identity, observation, result-cardinality, generation, operation-kind, retry-shape, uniqueness, lock, SQLSTATE/reason-code, and privilege validation. Do not duplicate allocation or exception policy in the RAES adapter. |
| RAES consumer and GCE planning: `raes_plan*.py`, `raes_gcp_adapter.py`, `raes_gcp_plan.py`, `gcp_range_cell_types.py` | Extend the existing process-local projection and neutral `RangeCellPlan`; validate static addressing and realized CIDRs before mutation. Reuse `RaesPlanError`/`RaesGcePlanError`, host assignment, ACL/service builders, naming, labels, and placement. |
| Network containment: `gcp_range_cell_firewall.py`, `raes_gcp_firewall.py`, `gcp_range_cell_escape_checks.py` | Render every allow from realized per-range CIDRs and range-scoped tags. The escape checker is a required rendered-plan test backstop; it is not currently a runtime policy gate. Never allow the tenant supernet as an intra-range/service source. |
| Provider realization: `gcp_range_cells.py`, `gcp_range_cell_resources.py`, `raes_gcp_apply.py`, `raes_gcp_destroy.py`, `raes_gcp_inventory.py` | Reuse deterministic range-ID-scoped names and labels, neutral ensure/delete primitives, cleanup compensation, and exact-resource inventory. Do not fork RAES-specific subnet/firewall provider clients. |
| Configuration and topology: `config/_range.py`, `config/_gce.py`, `platform/terraform/gcp/modules/platform-core`, GCP environment roots, `scripts/gcp/render_runtime_env.py` | Reuse `range_network_cidr` -> `RANGE_NETWORK_CIDR` and `range_network_id` -> `RANGE_NETWORK_ID`. Terraform's topology-disjointness checks and shared-VPC config validation remain authoritative. No new env variable or duplicate CIDR field is needed. |
| Job/OS boundary: `shared/cloud/kubernetes`, `shared/cloud/gcp/task_runner.py`, chart and raw `validatingadmissionpolicy-provisioner-jobs.yaml` | Keep argv limited to `raes-range`, action, request UUID, and operation UUID. CIDRs, address maps, payloads, credentials, and env maps do not enter argv. Existing literal ConfigMap env allowlists, image/command grammar, Workload Identity service account, restricted pod security context, mounts, and network policy stay unchanged. |
| Secrets and IAM: existing GCE secret helpers, Cloud SQL/IAM DB auth, provisioner database grants | The allocation contract is secret-free. Do not store CIDRs in a secret system, widen range-host IAM, expose credentials in assignment data, or grant table access to make reservation reads easier. |
| Errors, logs, and results: `shared.exceptions`, `RaesRealizationError`, `raes_range_ops._classify_failure`, `shared.operation_result_payloads`, `log_redact.py` | Report fixed reason codes and bounded authored diagnostics. Raw provider/driver messages, authored CIDRs/static IPs, resource locators, and reservation maps do not cross the durable result/public envelope or become metric labels. Internal logs correlate request/operation IDs and fingerprint resource names. |
| Cleanup truth: `raes_gcp_inventory.py`, Engine cleanup verification, ADR-063-R4/R5 | Inventory remains independent of the delete loop and reports `VERIFIED_ABSENT`, `RESIDUALS_FOUND`, or `INCOMPLETE` with bounded categories/scope. Only verified absence permits reuse. |

## Capacity, regional inventory, and operating limits

Terraform already defines and validates the tenant supernet, both checked GCP
environments already select `10.50.0.0/16`, and the runtime renderer already
publishes it. No second supernet setting is warranted. The allocation policy
reserves the first two `/24` blocks and excludes the final `/24`, so a `/16`
provides 253 allocatable `/24` slices, not 256. A range with multiple authored
networks consumes one slice per network. Capacity claims must use this effective
policy and provider quota, not raw CIDR arithmetic.

No repository automation currently raises GCP subnetwork or in-use-IP quota.
Quota headroom is therefore an explicit deployment prerequisite and scale-test
evidence item, not an allocator constant or a silently claimed Terraform result.

GCP subnet CIDR uniqueness is global to a VPC while the current provider-drift
adapter lists only one region. Multi-region placement means inventory must observe
all relevant regions (prefer an aggregate VPC-scoped read in the existing GCP
network inventory adapter), not whichever region happens to be in process env.
Any subnet inside the reserved supernet that can collide must be treated as
occupied; if the deployment permits non-Shifter subnetworks in that address
space, filtering solely on the Shifter label is insufficient. Keep this policy in
the provider inventory adapter, not in RAES planning.

Existing resource names, target tags, labels, guest-secret namespaces, addresses,
routers/NAT, and firewalls are range-ID scoped. The concurrency audit must verify
those incumbents under mixed users/events and multiple networks; it must not add
a new naming system merely for subnet allocation.

## Verification obligations

Focused tests must exercise the incumbent owners:

- subnet contract and real-PostgreSQL coordination tests: concurrent reservations,
  idempotent retry, changed shape, exhaustion, drift, fencing, read/release,
  effective privileges, and all-or-nothing multi-network allocation;
- RAES producer/provisioner parity and plan tests: fixed `/24`, open-only, mixed
  fixed/open, multiple networks, static offset rebasing, deterministic dynamic
  assignment, ACL/service/firewall use of realized CIDRs, malformed/duplicate/
  out-of-range assignments, unsupported and mixed prefixes, and no input mutation;
- operation/apply/destroy/inventory tests: provision compensation, warm activation,
  reconstruction, release-after-inventory ordering, no release for residual or
  incomplete inventory, and repeated create/destroy without leaked rows;
- GCP inventory tests: requested-network filtering and cross-region occupancy;
- live evidence: concurrent same-scenario and mixed-scenario ranges across users
  and events, all READY, distinct subnets, representative smoke, provider quota
  observations, verified teardown, and repeated reuse without exhaustion.

The repository-wide architecture guard remains mandatory. Changes to shared
contracts, migrations, runtime config, Terraform, chart/raw admission, or ADR
guardrails additionally run their native unit/PostgreSQL, import, Terraform,
Helm/Kubernetes, and provisioner suites. Mocked provider calls alone cannot prove
quota headroom or cleanup absence.

## Non-goals and prohibited shortcuts

- No VPC-per-range migration, public API/RAES transport change, new requirement,
  new allocation table, generic IPAM service, or second cleanup state machine.
- No mutation of authored `range_config`, no CIDR allocation through asynchronous
  operation results, and no direct provisioner access to Engine tables.
- No literal reuse of authored CIDRs in shared-VPC mode, random/hash-only CIDRs,
  process-local occupancy caches, or provider-create-and-retry collision loops.
- No scalar allocation threaded through only provision while activation, destroy,
  inventory, ACLs, or service firewalls reconstruct something different.
- No `/28` truncation of a `/24`, silent loss of static addresses, modulo/wrapping
  of host offsets, lenient dropping of malformed properties, or widening a
  firewall to make rebasing work.
- No release in `finally`, before inventory, after an incomplete inventory, or
  merely because the logical range reached a terminal status.
- No quota value hard-coded as address capacity, no claim that `/16` means 256
  usable `/24`s under the existing policy, and no single-region drift observation
  presented as global-VPC safety.

ADR-043-R4/R6 and ADR-063-R4/R5 already decide the persistence, realization, and
cleanup boundaries above. This issue needs this focused design note, not a new
ADR or exception, unless implementation intentionally changes one of those
accepted rules.
