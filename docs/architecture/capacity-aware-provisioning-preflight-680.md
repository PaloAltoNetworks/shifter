# Capacity-Aware Provisioning Preflight — Issue 680

**Requirement:** PLAT-201
**Status:** pre-implementation guidance
**Scope:** capacity admission for event-driven range provisioning; this is not an implementation plan.

## Boundary decision

CTF owns organizer-authored event intent. CMS continues to own authenticated range
creation, scenario hydration, and backend admission. Engine owns the final
capacity assessment, durable reservation, and admission decision. The
provisioner realizes an already-admitted request; it must not recreate capacity
policy or make a second, divergent admission decision.

An event declaration is not an allocation. `CapacityDeclaration` remains the
append-only record of intent. An accepted assessment must be an immutable,
fresh snapshot pinned to the declaration revision, target partition, policy
version, and observed-at time; its reservation must be durable and atomically
account for other overlapping event reservations. This is capacity state, not a
new range lifecycle, request workflow, or `ResourceStatus`.

The existing `request_id` remains the only provisioning-launch correlation ID.
Event identity and declaration revision are trusted event-capacity context that
travels alongside the existing CTF-to-CMS-to-Engine create request. They are
not encoded in `RangeSpec`, a scenario document, a provisioner command, or a
new job/operation ID. All event-scoped creation paths must carry that context:
participant batch creation, direct participant creation, spare creation, and
replacement/recovery creation.

## Contracts, validation, and placement

`capacity_hints` is currently an organizer JSON object and is advisory input,
not provider allocation data. A typed, bounded capacity declaration and demand
contract crossing CTF, CMS, and Engine belongs in native `shared`; the existing
Engine-owned `EventCapacitySignal` should be adapted or re-exported rather than
creating a second cross-layer schema. Validation is required both at the
organizer/API boundary and at the authoritative Engine service boundary:

- bounded named fields and enums, non-negative counts, and ordered event
  windows;
- no arbitrary provider resource names, account IDs, regions, role ARNs, or
  executable configuration from organizer input;
- no reliance on the frontend's current invalid-JSON-to-`{}` fallback, model
  `JSONField`, or dataclass annotation as authoritative validation.

Demand must be derived from the canonical hydrated launch artifact: the
existing scenario and `RangeSpec` path for legacy ranges and the existing
`ProvisioningPlan` path for ACES-native ranges. It must reuse the backend image
resolver/profile rather than copying scenario YAML or creating a parallel AMI
mapping. Per-image output is demand keyed by resolved immutable image/profile
identity (with a logical source only for diagnostics). It is not itself a
consumable quota: reusable AMIs count against headroom only where a provider
catalog defines a real inventory or quota metric.

A target partition is deployment-owned, allowlisted configuration, selected
from the admitted backend and bound range target. It needs a stable name and a
typed tuple such as provider, account/project, region, immutable backend, and
capacity-policy profile. It must never be inferred from an event name,
scenario, organizer hint, CLI argument, or mutable global provider setting.
Reuse the existing write-once `Range` backend/purpose binding and the GCP range
target-project seam; record the assessment's target snapshot so later retry,
destroy, and reconciliation cannot drift when configuration changes.

## Assessment and admission semantics

Each provider metric must have an explicit catalog entry: dimension and unit,
partition, measurement source, freshness limit, safety margin, and enforcement
mode. Do not call all shared-resource limits "quota"—for example, Bedrock
throughput, NAT bandwidth, SSM concurrency, and IAM capacity have different
units and observation models.

For a detectable metric, assess available capacity as observed provider limit
less observed usage, committed overlapping reservations, and the configured
safety margin. Provider reads happen outside database transactions; Engine then
performs a transactional recheck and records the reservation. Provider state
cannot be locked, so freshness bounds and safety margins are required.

The policy result is `admitted`, `warning`, or `rejected`, with a bounded reason
code per metric. A known over-limit metric never silently proceeds: an enforcing
policy rejects before launch, while an advisory policy emits a visible operator
warning and audit record. Unsupported, unavailable, or stale measurements are
`indeterminate`, never silently converted to either zero usage or sufficient
headroom. Any future privileged override must be explicit, authorized, and
audited; it is not an organizer-provided hint.

Capacity-sensitive changes invalidate the prior assessment/reservation before
spinup: roster, spare count, scenario or range configuration, event window,
placement policy, and typed hints. In particular,
`provision_event_spares` currently declares capacity before persisting the new
spare target; it must not assess the stale value. Cancellation, terminal
cleanup, and retry/reconciliation must release or reconcile reservations
idempotently against existing request IDs.

## Cross-cutting incumbents to reuse

- CTF declaration: `ctf.services.range.capacity`, its bridge in
  `ctf.bridges`, and the existing organizer serializer/permission path.
- CMS admission and persistence: `cms.services.create_range_dispatch`,
  `cms.services._range_create`, canonical scenario hydration, and
  `shared.range_instantiation_policy.BackendAdmission`.
- Engine durable orchestration: `engine.services.create_range`,
  `engine.models.Range`, `engine.models.CapacityDeclaration`, and the existing
  request-id idempotency/generation-fencing path.
- Cloud/configuration: the closed `installation` backend bundle and
  `BackendCapability` registry, `config._runtime_env.resolve_cloud_provider`,
  and `shared.cloud` adapters. A read-only capacity-inventory capability, if
  needed, belongs in that factory—not in CTF, CMS, or a new provider router.
- Launch security: `engine.ecs` launch intents and command validation,
  `engine.ecs._env`, and `shared.cloud.sensitive_env`. Capacity state stays
  before dispatch; only the request ID belongs in process arguments.
- Safe reporting: `shared.errors`, `shared.api.errors`, CTF's existing API
  error helpers, `shared.audit`, and `shared.log_sanitize`/provisioner
  redaction. Use their bounded codes and safe fields rather than raw provider
  errors or a parallel exception hierarchy.

## Security and operational guardrails

The organizer API must retain its existing event ownership and write-scope
checks. CMS must continue to receive only server-derived range data, and Engine
must perform the final authoritative validation after CMS admission. Installation
configuration validates allowed partitions and provider capabilities before use;
the cloud adapter validates provider response shape before it reaches capacity
policy.

Capacity readers require separate least-privilege, read-only identities per
target partition. Do not expand the CTF scheduler, portal, worker, or
provisioner identity to broad compute, secret, or cross-account privileges just
to inspect headroom. Cross-account AWS reads require a constrained read role;
cross-project GCP reads require narrowly scoped project/API permissions. No
credential, quota payload, raw provider response, account identifier where
sensitive, or capacity policy blob may be placed in task arguments, task
environment, logs, audit free text, or API error details.

API rejection and warning surfaces use the existing standard error envelope and
safe reason codes with request correlation. Audit and logs record decision,
partition-safe identifier, bounded resource code, and counts/fingerprints only.
The unrelated portal saturation metrics in `config.capacity_metrics` remain
observability only; they are not the capacity planner or reservation store.

## Explicit non-goals

- autoscaling, cost/billing controls, generic cloud-placement optimization, or
  cross-cloud migration;
- replacing provider quota systems, claiming atomic provider-side reservation,
  or fabricating headroom for unsupported metrics;
- a new organizer-controlled account/region/provider routing surface;
- duplicating scenario/image resolution, lifecycle statuses, request IDs,
  provider clients, exception trees, or background workflows;
- exposing raw headroom, quota limits, infrastructure topology, or provider
  diagnostics to participants or unprivileged organizers.
