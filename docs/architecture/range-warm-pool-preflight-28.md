# Range warm-pool architecture preflight (#28)

## Purpose and decision

This note constrains implementation of a deployment-owned warm pool for initial
Mission Control and CTF launches. It is architecture guidance, not an implementation
plan. Cold provisioning remains the semantic baseline.

A warm pool is a provider-neutral allocation policy above the existing range substrate:

1. reconciliation may provision a system-owned, quarantined generation for one exact
   immutable compatibility key;
2. launch performs all ordinary authentication, tenancy, scenario, backend, access, and
   capacity gates, then atomically claims one matching ready generation;
3. after commit, the existing durable operation workflow activates that generation for
   the claimant with fresh credentials and access; and
4. a miss, race, disabled policy, or unsupported capability uses the unchanged cold
   path with the inputs already validated for that launch.

The core `range-substrate/v1` stays at `provision`, `destroy`, `pause`, and `resume`.
Warm preparation is a closed, trusted profile of `provision`; claimant activation is
the optional `range-warm-activation/v1` capability in ADR-039. Atomic claim is not a
provider operation. Cleanup always uses canonical `destroy`.

## Domain and persistence boundaries

The warm allocation ledger belongs with Engine range orchestration. It references the
existing Request/Range generation; it does not replace Engine or CMS range state and
does not add a public lifecycle enum. Its private allocation states must distinguish at
least provisioning, ready/unclaimed, claimed/activating, unhealthy/quarantined, and
retiring/terminal. A row and database constraints, not an in-memory queue or provider
tag, are the claim authority.

The claim transaction must:

- select a ready, unclaimed, exact-fingerprint generation with row locking (the CTF
  `_claim_spare` use of `select_for_update` is the concurrency precedent);
- use a deterministic lock order and a conditional ready/unclaimed transition so two
  launches cannot claim the same generation;
- repeat the canonical locked workspace authorization and preserve CMS's active
  `(user_id, range_source)` uniqueness constraint;
- update CMS `RangeInstance`/`Request` and Engine `Range`/`Request` ownership and
  workspace projections together through public service facades, and persist strict
  claim audit evidence in that transaction; and
- roll back all ownership and claim changes on conflict. It must commit before queueing
  activation and must never call a provider while holding database locks.

`cms.services._range_reassign` and `engine.services._range_by_request` are useful
projection-update precedents, but their current safety test only blocks a range with a
VPN binding. They are not a warm-claim primitive: warm activation must replace all
user-specific access and runtime residue, and the claim needs stronger range/pool locks
and generation fencing. Reuse or extract their ownership/workspace projection logic;
do not call the CTF recovery helper or weaken its semantics.

The legacy `shared.schemas.RangeSpec`/`RequestSpec` persists `user_id`. Reassigning a
generation built from that intent would make immutable intent disagree with its owner.
Legacy generations therefore remain ineligible and cold-fallback until a separately
versioned ownership-neutral intent is introduced. Do not strip, mutate, or clone
`range_spec` to bypass this. RAES `shared.raes.operation_input` is the viable incumbent
because its immutable provider projection deliberately excludes `user_id`.

## Typed policy and compatibility

Operator policy belongs in the root `shifter.yaml` contract and
`shifter/installation` schema/loader/registry/publication machinery, following the
provider-neutral `range_egress` pattern. It must be closed (`extra=forbid`), typed once,
and default disabled/zero. It must reject rather than normalize unsafe values:

- `0 <= minimum <= target <= maximum` and deployment-owned cost/capacity ceilings;
- bounded positive reconciliation cadence and concurrency, finite idle lifetime, and
  closed replacement/scale-down strategies;
- unique pool/bucket identities and only declared capacity partitions/metrics; and
- no provider credentials, account/project overrides, command fragments, or arbitrary
  extension dictionaries.

`target` is the desired ready count, `minimum` is an operational shortage threshold,
and `maximum` is a hard ceiling. The ceiling applies to all nonterminal unclaimed
generations (ready plus provisioning) so concurrent reconciler passes cannot create an
unbounded in-flight overshoot. A capacity/cost refusal may leave the pool below minimum
and must alert; minimum is never authority to bypass a ceiling. Scale-down removes only
unclaimed entries and converges toward target without retaining an unsafe or expired
entry merely to satisfy minimum.

Render one non-secret, validated runtime projection only to the portal/reconciler that
owns policy. If a runtime environment key is added, update together the installation
published contract and inventories, renderer, `config/_env_manifest.py`, generated
`config/env-manifest.json`, settings parser, Helm values/templates, GCP overlays, and
their parity tests. Do not send policy JSON to the provisioner or place it in argv.
Persist the exact effective-policy fingerprint and immutable operation input used for
each generation so a later config change cannot reinterpret it.

Compatibility is a canonical digest computed after incumbent validation and backend
admission. Its normalized input includes:

- admitted provider/backend plus persisted capacity partition and placement
  region/zone class;
- `InstantiationPurpose`, product/range source, workspace isolation class, egress and
  participant-access mode;
- exact RAES package and lock digests, serialized `ProvisioningPlan` digest, and the
  exact resolved image, content, and artifact binding digests; and
- topology/resource mix, NGFW/shared-resource posture, lease/access requirements, and
  every other immutable input that affects resources, bootstrap, or isolation.

Reuse the digest/canonicalization rules of RAES package loading, operation envelopes,
and image/artifact binding. Do not introduce a second scenario parser. Scenario IDs,
image aliases, mutable registry rows, provider defaults, or caller-supplied keys are not
compatibility proof. A changed key makes old ready generations incompatible and the
reconciler retires them through destroy.

Event/workspace overrides are optional scope for #28. Preserve the seam as a pure
`deployment policy + optional narrowing override -> effective policy` resolution:
overrides may disable, reduce counts/concurrency/ceilings/lifetime, or restrict eligible
buckets; they may never expand a deployment maximum, select another backend/partition,
or weaken isolation. Authoritative resolution and validation occur server-side under
the same workspace/event lock used by launch.

## Capacity, cost, and reconciliation

Reuse `shared.capacity` and the Engine capacity assessment/reservation/draw ledger.
Current rows and services are event-shaped, so generalize their owner/scope seam or add
a pool-scoped sibling inside the same Engine capacity boundary; do not fabricate a CTF
event and do not create a parallel quota system. The capacity catalog remains the only
source of partitions, units, freshness, safety margins, and enforcement. Estimated
cost must be an explicitly declared catalog metric/unit, not an inferred universal
currency value.

Admission occurs before each warm provision. A warm generation keeps its draws while
ready and after claim; ownership transfer does not release capacity. Unhealthy,
expired, incompatible, and excess generations retire via canonical lifecycle, and
capacity/cost is released only after reconciliation observes provider absence. Failed
activation must not trigger an overlapping cold provision unless capacity admission
explicitly covers both the suspect generation and replacement.

The warm reconciler follows the existing managed-worker conventions in
`cms/management/commands/reconcile_range_events.py`,
`engine/management/commands/drain_provisioner_launch_outbox.py`, and the operation
result applier: bounded batches, heartbeat, row locking/`skip_locked`, generation
fencing, idempotency, bounded backoff/jitter, and crash-safe retry. It computes desired
state from persisted policy/ledger data, but performs no provider I/O in a transaction.
Provision and destroy travel through existing durable intents and canonical lifecycle.
The one-shot, event-specific `ctf_scheduler` and `CTFScheduledTask` are not the owner.

The existing CTF recovery pool remains semantically separate: it is event-scoped,
budgeted with participant recovery capacity, and claimed only after participant-range
failure. Shared low-level capacity, locking, lifecycle, audit, and adapter helpers are
welcome; shared policy/status models that erase initial-launch versus recovery intent
are not.

## Cross-cutting layers and required incumbents

| Layer | Canonical incumbent | Warm-pool obligation |
| --- | --- | --- |
| HTTP authentication and authorization | `mission_control.api.ranges.LaunchRangeView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, lifecycle permission/rate throttle; CTF participant/event gates | Run unchanged before any claim. HTTP cannot supply pool, owner, workspace, backend, fingerprint, or capability facts. |
| Launch validation and tenancy | `cms.services._range_launch_common`, `_range_workspace`, `_range_backend_admission`; CMS active-range constraint | Hydrate and validate once, reauthorize the bound workspace under lock, then try warm claim before the existing cold create branch. A miss must not rerun divergent validation. |
| Immutable scenario/input shape | `shared.schemas` for legacy; RAES package/lock digest, `ProvisioningPlan`, `shared.raes.operation_input`, image/artifact/content/access bindings | Compose existing contracts and digests. RAES-only eligibility until ownership-neutral legacy intent exists. Never persist a second topology DTO. |
| Backend/capability selection | `shifter/installation` registry and `shared.range_instantiation_policy`; persisted `Range.range_backend` | Advertise warm activation per exact adapter/resource mix. Unsupported means cold fallback before warm mutation, not emulation. |
| Allocation and ownership persistence | Engine Request/Range and CMS Request/RangeInstance; CMS/Engine public service facades; CTF row-locking precedent | Database-backed single claim, consistent ownership/workspace projections, active-range uniqueness, generation fencing, no direct cross-layer model writes. |
| Durable task/result workflow | `ProvisionerLaunchIntent`, `OperationInput`, `shared.operation_envelope`, `OperationResultInbox`, result applier, range-event outbox | Enqueue after claim commit; use operation idempotency and apply provider result, audit, and user lifecycle projection transactionally. Update every closed operation validator if `activate` is transported. |
| Provider lifecycle | ADR-039 adapter, existing `provision`/`destroy`, optional `range-warm-activation/v1` | Warm prepare suppresses participant access; activate rotates/scrubs then proves readiness; destroy handles every retirement. No pool-specific deletion path. |
| Capacity | `shared.capacity`, Engine assessment/reservation/draw services and database constraints | Admit before provision, hold while resources exist, account for claim/failure overlap, and release after observed absence. Do not mix CTF recovery-spare counts with initial-launch pool targets. |
| Secrets and access | `shared.remote_access`, `shared.raes.participant_access`, provider secret stores, provisioner secret adapters, Engine terminal resolvers, Mission Control Guacamole builders | Persist references only. Pre-claim exposes no participant access; activation creates fresh owner/generation material and access surfaces recheck current owner/state. |
| Events and reconciliation | ADR-025 `RangeEventOutbox`, `range.status.updated`, CMS handlers/reconciler | Reuse public lifecycle events; keep private allocation state internal. Notification is not proof of provider success. |
| Audit | `shared.audit` vocabulary/writer and strict transactional audit convention | Record bounded policy/reconcile, prepare, claim, hit/miss/fallback, activation, failure, and cleanup facts with trusted actor/system attribution. Intent precedes non-rollbackable side effects. |
| Errors | ADR-039 classified failures, `CMSError`/`EngineError`, `shared.errors`, `shared.api.errors.api_error_response` | Pool miss/race is a normal branch. Map failures once to stable safe codes; API receives the canonical envelope, never raw provider diagnostics. |
| Logging and metrics | ECS JSON logging, `shared.log_sanitize`, provisioner `log_redact`, provider-aware capacity metric publishers | Structured bounded fields and low-cardinality dimensions only; sanitizing log injection is not permission to log secrets or provider payloads. Reuse metric-provider selection, not a new AWS/GCP publisher. |
| Deployment/runtime policy | config environment manifest, Helm/GCP worker manifests, K8s ValidatingAdmissionPolicy, PSS/network policy | Keep portal/reconciler policy non-secret; keep provisioner Jobs pinned, non-root, read-only, drop-all, exact-env and exact-argv. Chart and raw GCP admission policies must stay structurally equivalent. |

## Security gates from request to operating system

Every warm claim and activation crosses all of these gates:

1. **Request gate:** existing authentication, token scope/session, actor permission,
   CSRF where applicable, lifecycle permission, rate throttle, serializer, scenario
   ownership/catalog, and CTF event/participant state checks run unchanged.
2. **Tenant/config gate:** CMS resolves the workspace from trusted context, authorizes
   the operation, validates egress/access and backend admission, and rechecks tenancy in
   the claim transaction. Root installation policy supplies maxima; request data cannot.
3. **Shape gate:** installation Pydantic models reject unknown policy; RAES package,
   plan, image/artifact/content/access parsers and `OperationInput`/operation-envelope
   validators reject unknown, stale, oversized, or digest-mismatched data before cloud
   or guest mutation. Any new activation payload has one closed versioned parser in
   `shared`, imported by producer and provisioner.
4. **Secret/access gate:** operation inputs, database state, events, metrics, and logs
   contain references and bounded metadata only. `shared.raes` secret-looking evidence
   validation remains in force. Secret stores are resolved only at the provisioner or
   current-owner terminal/Guacamole boundary.
5. **Provider identity gate:** the provisioner workload identity remains least
   privilege and mutations prove installation/request/generation ownership. Warm
   support is capability evidence, not inferred from provider name.
6. **OS/admission gate:** Jobs retain the pinned image and entrypoint, exact env
   allowlists, ephemeral secret, non-root/read-only/drop-all runtime profile, network
   policy, timeout, and exact structured command grammar. Only resource/operation plus
   request and operation UUIDs may appear in argv; no owner, email, workspace, policy,
   compatibility data, resource identifiers, or secret references. Adding `activate`
   requires synchronized CLI, launch-intent, operation-envelope, Helm admission, raw
   GCP admission, and structural-parity tests.
7. **Error/output gate:** provider exceptions are classified to ADR-039 codes and
   bounded sanitized diagnostics in the operation result. Public HTTP/websocket
   surfaces use the existing error envelope and events; they never receive raw errors,
   credentials, provider payloads, or inventory.

Activation's security postcondition is stronger than ownership reassignment. It must
rotate or remove any bootstrap/system guest accounts and keys, local/domain passwords,
SSH/RDP material, VPN identities, Guacamole sessions/tokens/bindings, provider IAM or
service-account grants, signed URLs, participant firewall bindings, and user/runtime
content. Readiness requires both fresh claimant access and a negative check that prior
references and paths no longer work. If an adapter cannot prove that for the complete
resource mix, that mix is unsupported and the generation is destroyed rather than
claimed or re-pooled.

## Observability and verification guardrails

Metrics expose ready/provisioning/unhealthy counts, claims/hits, bounded fallback
reasons, activation failures, claim and cold launch latency, observed improvement,
idle-age distribution, and catalog-derived estimated cost. Labels may include a bounded
pool profile, backend/region class, product, and closed outcome/reason; never user,
request, arbitrary scenario, resource, account, or project identifiers. Keep warm-pool
metrics in a distinct namespace from portal-capacity and capacity-planning metrics,
while reusing their injected CloudWatch/GCP publisher seam.

Tests must exercise the shared contract and failure boundaries, not only service happy
paths: real PostgreSQL concurrent claims and active-range conflicts; empty/disabled and
unsupported fallback; exact compatibility mismatch after scenario/image/config change;
replenishment, scale-down, expiry, unhealthy cleanup, provider-absence confirmation,
and capacity refusal; claim/activation crash points, retries, stale result fencing, and
partial provider failure; strict audit and bounded errors/metrics; old-owner access
denial, credential/reference rotation, Guacamole/VPN/session invalidation, and no
cross-tenant runtime residue. Reuse the operation/admission/conformance suites and keep
Helm/raw-GCP manifest parity. SQLite is insufficient evidence for locking and partial
unique-constraint behavior.

The shipped operator documentation must update `docs/features/ranges.md` and the CTF
organizer guidance (plus deployment-specific configuration documentation) with policy
semantics, sizing and latency/cost tradeoffs, supported adapter/resource mixes,
capacity-refusal behavior, metrics/alerts, scale-down/expiry, and the explicit
distinction from the CTF recovery-spare pool. Capability claims must come from the
registry/conformance evidence, not a hand-maintained provider claim in the UI.

## Whole-repository scope

- operator contract: `shifter/installation` schema, loader, contract, registry,
  `range_egress` precedent, runtime inventories, renderer, publication snapshots,
  root `shifter.yaml`, and installation examples/tests;
- runtime config: `shifter/shifter_platform/config/_env_manifest.py`, generated
  `config/env-manifest.json`, settings and capacity configuration/metrics adapters;
- shared contracts: `shared.capacity`, `shared.range_instantiation_policy`,
  `shared.operation_envelope`, RAES operation/binding parsers, remote access, audit,
  errors/API envelopes, cloud task/metrics seams, and import boundaries;
- product/CMS entrypoints: Mission Control launch API; CTF provision/bridges/recovery
  spares/capacity; CMS launch/workspace/backend/reassignment services and models;
- Engine: range/request/capacity/operation-input/launch-intent/result-inbox models and
  services, result applier, event outbox, and reconcilers;
- provisioner: CLI, operation input/result validators, range adapters/runners,
  credentials/access/content setup, state/ownership evidence, logging/redaction, and
  adapter conformance tests; and
- deployment: Helm and raw GCP worker/config/admission/network-policy manifests,
  generated/parity tests, plus ADR/import/security guardrails.

## Gotchas and prohibited designs

- Do not equate Engine/CMS `READY` with pool-ready. A prepared generation is quarantined
  and inaccessible until activation succeeds; pool allocation state stays private.
- Do not reuse `CTFSpareRange`, `SpareRangeStatus`, `CTFScheduledTask`, event
  `spare_range_count`, or recovery categories as the initial-launch pool model.
- Do not make a synthetic event/declaration to fit the current capacity schema, or
  count a recovery spare and warm initial-launch generation as one policy.
- Do not claim by read-then-write, provider tag, cache, or queue visibility; do not call
  providers inside the claim transaction.
- Do not treat owner-column reassignment, VM stop/start, snapshot restore, or a new
  password alone as tenant sanitization. Never return a claimed/suspect generation to
  the pool.
- Do not mutate legacy persisted specs, use scenario/image aliases as compatibility,
  let a config reload reinterpret an existing generation, or duplicate RAES/image
  validation.
- Do not fork Mission Control and CTF launch workflows. The claim attempt belongs in
  canonical CMS orchestration after product gates, with the exact cold path as fallback.
- Do not add provider branches above the adapter registry, provider-specific pool DTOs,
  a second exception hierarchy, public pool lifecycle statuses, a second event bus, or
  adapter-local cleanup.
- Do not free capacity at claim or destroy request time, and do not cold-fallback after
  failed activation while orphaned capacity is unaccounted.
- Do not put policy, user/tenant identity, provider inventory, or secrets in argv/env,
  operation diagnostics, audit context, logs, events, or metric dimensions.

## Non-goals and implementation boundaries

- This issue does not change public launch request/response semantics, authentication,
  workspace roles, scenario authoring, or provider selection.
- It does not merge or redesign the CTF recovery-spare policy, nor retroactively make
  that workflow satisfy warm initial-launch isolation semantics.
- It does not make every backend/resource mix warm-capable. Explicit unsupported
  capability plus cold fallback is compliant; legacy ownership-bearing intent is
  initially in that category.
- It does not introduce cross-provider migration, snapshot portability, pause/resume
  emulation, image baking, or reusable user runtime state.
- It does not promise exact monetary billing; cost is a bounded catalog-derived
  estimate used for policy and observability.
- It does not require event/workspace overrides in the first delivery. If added, they
  only narrow deployment-owned policy through the reserved resolver seam.
