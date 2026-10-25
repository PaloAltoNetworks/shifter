# ADR-060: Model allocation and request budgets are Engine-owned commitments

## Status

**Superseded by [ADR-068](068-model-access-broker-parked.md) (2026-10-05):** the broker is parked and not supported for use; keyless-direct (ADR-064) is the only live model path. This record is kept as history of the parked implementation.

Proposed for [#681](https://github.com/Brad-Edwards/shifter/issues/681),
PLAT-202, 2026-09-06. Depends on ADR-059; runtime implementation is pending.

## Context

ADR-047 already assigns capacity assessment, reservation, and range draws to
Engine. Its advisory mode and the CTF bridge's best-effort error handling
cannot be reused as a security budget. Event demand, provider throughput,
application spend, and in-flight request concurrency are distinct quantities.
Provider usage and billing reports arrive too late to authorize each call.

## Decision

Extend the existing declaration/catalog/assessment seams with typed model
demand and separately named quota pools. Engine selects an eligible shard
using a versioned strategy, reserves its capacity, and persists an immutable
allocation before dispatch. Eligibility includes model/protocol compatibility,
approved provider/account/project, region and data handling, health/freshness,
and available budgets. Assignments remain stable for the admitted generation;
retry never reruns an unrecorded modulo assignment. Models or credentials
sharing one provider quota pool do not create extra quota.

Sharing is independently configurable across explicit range sets, CTF
events/cohorts, a user's ranges, typed groups, named collections or all ranges
within one deployment. Each binding selects shared profile, provider identity,
per-alias routing affinity, capacity and monetary/rate/concurrency pools.
Partial sharing and sharing all these resources are both supported; each
range retains an independently revocable grant. Snapshot/dynamic membership,
canonical group ownership and revision fencing are explicit contracts.

Overlapping bindings apply all mandatory restrictions and distinct accounts.
Operator priority resolves non-combinable choices; conflicting ties reject.
Shared assignments are persisted once per affinity group, and common capacity
is reserved once rather than once per member. Each request locks/reserves/
settles the set of applicable account IDs once. Shared-only budgets need no
equal per-range partition; optional individual caps tighten the common pool.
Membership changes cannot reset spend, transfer unresolved liability, bypass
authorization or leave old grants usable while reassessment runs. The
[sharing contract](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/sharing.md)
defines selectors, bounded resolution, precedence and management behavior.

Model-required launches need successful enforcing model admission even when
general compute planning is disabled or advisory. Missing declarations,
policy, prices, measurements required by policy, or accounting availability
fail closed. Optional model access can be visibly unavailable only when the
admitted scenario explicitly permits that outcome.

Keep model spend and request accounting in Engine-owned tables associated
with existing operations and capacity draws. They are not another range
lifecycle. Use integer monetary units, immutable pricing revisions, explicit
rate-window boundaries, conditional updates/row locks, uniqueness and check
constraints. Reserve a conservative upper bound before any potentially
billable provider invocation. Simultaneously enforce all applicable deployment,
event, user/group/collection, configured range, grant and quota-pool limits.
Finite deployment and per-request bounds remain mandatory. Do not use the
capacity models' floating-point quantities for money.

Record dispatch intent before transport. A worker lost around dispatch leaves
an unknown outcome and a retained charge reservation; another worker must not
blindly repeat the call. A repeated client idempotency key with changed intent
conflicts. A response body is not retained for replay. Stream disconnect,
timeout, missing usage, and unproven cancellation never refund presumed spend.
Settle proven usage once, or conservatively charge the reserved bound after
the deadline while retaining the unknown outcome and reconciliation evidence.

Provider capacity remains external and non-atomic. Application budgets bound
approved requests at validated price bounds; they do not promise an exact
cloud invoice cap. Unknown billable features and models without a defensible
upper bound are disabled. The
[accounting contract](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/architecture.md#request-admission-and-accounting)
defines race, retry, stream, and reconciliation behavior.

## Alternatives and consequences

Post-hoc alerts cannot prevent overspend. Per-process or Redis-only counters
lose authority across restart/failover. Recomputing assignments per call makes
capacity, residency, and teardown drift. These are not selected.

Synchronous PostgreSQL admission adds latency and contention. Ordered locking,
bounded requests, and measured cohort limits are the initial scaling choice.
There is no automatic queue or distributed credit system. An inability to
meet the qualified envelope requires a new implementation decision with
equivalent enforcement, not an unreviewed fail-open cache.

Tests must exercise real PostgreSQL contention, duplicate and stale requests,
crash recovery, budget reductions, and disconnects against controllable
provider boundaries. Existing ADR checks alone do not establish these claims.

M02 (#2119) implements the launch-time admission decision this ADR requires:
required model access is enforced fail-closed at the CTF→CMS→Engine launch seam,
independent of the best-effort PLAT-201 capacity path, while the broker,
allocation persistence, request accounting, and live provider admission remain
later milestones. One decision refines this ADR's "extend the declaration/catalog
seams with typed model demand": the per-pack scenario need is authored in a
Shifter-owned, digest-bound `ScenarioModelNeeds` overlay that rides the runtime
pack lifecycle, not in the deploy-time mounted catalog, so a newly registered
model-requiring pack is admissible without an operator catalog redeploy; the
catalog keeps owning the deployment policy (profiles/shards/sharing) the need
references. The M02 admit/deny verdict is a deterministic recompute (no persisted
decision yet); the zero-egress admitted-broker exception and the
demand-strategy/allocation threading are revisited when the broker capability
lands. See
[architecture § Launch-time model admission](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/architecture.md#launch-time-model-admission-m02-2119).

The [M03 allocation preflight](../architecture/model-access/allocation-preflight-2120.md)
records the current repository gaps and applies this decision to atomic
launch-intent persistence, real-quota serialization, authoritative sharing
resolution, generation-scoped release and configuration/error boundaries.
Existing compute-capacity helpers and sharing previews do not by themselves
establish those enforcing guarantees. This guidance does not change the ADR's
proposed status or claim runtime enforcement.

M03 (#2120) adds the [durable allocation boundary](../architecture/model-access/allocations.md).
The explicit provider-pool-to-shard inventory uses `model-access-policy/v2`;
v1 catalogs retain their original digests. Provider pools restrict eligibility
without creating quota. Engine joins exact reservations, immutable snapshots and
non-usable pending grants to the existing launch transaction. CTF-owned spare
preparation uses explicit event/spare authority for inactive system accounts;
it neither activates those accounts nor authorizes participant use. Warm-pool
preparation uses a distinct authority bound to its existing generation ledger.
Claim revokes preparation grants atomically before fresh claimant admission;
it does not transfer system authority or enable the managed account. Broker
request accounting and live qualification are not established by these changes.
The durable preparation identity binds the captured package needs and catalog
digest for lifecycle refresh. Native range pause/resume remains the executor;
local development dispatch drains the same outbox only after transaction commit.
Range selector freshness is distinct from generation-stable launch authority:
routine status transitions do not revoke their own or sibling model grants,
while ownership, destruction and owner-service mutations remain revoking fences.
