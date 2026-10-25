# Durable model allocations

Issue #2120 implements Engine-owned quota allocation and non-usable pending
grants. It extends ADR-047 assessments with exact-integer model reservations
and draws, joined to the existing operation-input and launch-intent transaction.
It does not issue credentials or enable broker calls. PLAT-202 remains a wider
capability tracked by #681.

## Provider-pool catalog

`model-access-policy/v2` adds a required `provider_pools` inventory. Each entry
contains `provider_pool_id` and a nonempty, unique `shard_ids` list. For example:

```json
{
  "provider_pool_id": "classroom",
  "shard_ids": ["vertex-primary", "vertex-secondary"]
}
```

This fragment belongs in the catalog's `provider_pools` array. Both shard IDs
must exist in that catalog. A sharing pool's `provider_pool_ref` names one
entry; allocation intersects its members with the alias candidates. A provider
pool is an eligibility restriction, not another quota or financial account.
There is no inferred membership, naming convention, or private fallback.

The installer and runtime accept v1 and v2 through their versioned schemas and
the same canonical validator. v1 normalization and digests are unchanged.
A v1 allocation with a provider-pool restriction fails closed because v1 has no
membership inventory. Pool membership is part of the v2 digest and immutable
allocation snapshot; editing the catalog cannot move an existing allocation.

## Admission and replay

CMS captures the package digest used by dispatch, resolves the authored needs
against that snapshot, and supplies the actual owner, workspace and typed
event, standalone lease, or warm-ledger scope. CTF supplies strict event demand,
the original draw identity and its event window. Required admission rejects
missing policy, stale authority, zero egress, unknown health, unsupported quota
units, exhausted capacity or prices that do not cover the commitment window.

The Engine preparation record is the lifecycle routing identity after the first
preparation. CMS refreshes its pinned package needs rather than re-reading a
mutable scenario overlay, and rejects a package-digest mismatch. The preparation
digest binds both that closed intent and the catalog digest, so a catalog-only
change is a new preparation revision. Replacement is allowed only for an
explicit lifecycle renewal with no surviving pending grant. If policy is removed
from an existing optional preparation, Engine revokes its grant and persists an
operation-scoped `ModelOptionalAbsence`; it cannot fall back to the old catalog.
The first optional launch with no policy also stores a catalog-free denied
preparation before dispatch. Its operation therefore remains absent on replay
even if policy becomes available later; a new lifecycle generation must renew it.

Qualified observation producers call `record_model_observations` outside any
database transaction. Observations retain provenance and catalog identity;
admission rechecks freshness after lock waits. No provider SDK runs in admission.

Engine holds the existing Range generation mutex, a shared policy-publication
fence, membership projections and owner fences, affinity groups, then physical
quota identities in canonical order. Independent quotas can progress together.
Overlapping half-open windows count all independent commitments against the
same physical quota, including renamed pools across catalog revisions. Shared
capacity accounts have one parent per quota/window, with bounded workload
budgets and child draws. Overlapping selectors do not duplicate a parent.

Fixed and weighted-rendezvous selection use the canonical M01 strategy. Shared
first use pins the alias assignment under the group lock; an incompatible
member rejects instead of changing that assignment. The allocation retains the
complete alias map, catalog, scenario need, prices, effective policy, provider
references, owner/event identity and binding/pool/membership revision vector.
Exact retries reuse it. Changed intent, withdrawn authority or expired grants
cannot turn a replay into a new allocation. Optional absence is recorded too.
Admission-unavailability outcomes such as authority, egress, quota-unit,
capacity, policy and price denial become replay-stable absence only for an
optional need. Generation, owner, deployment, malformed-intent and conflicting
replay failures remain fatal.

## Preparation authority and lifecycle

CTF creates the spare record before launching it, so sharing selectors and
system preparation use its real identity. Under the event/spare locks, CTF
projects explicit authority for an unconsumed spare's inactive, passwordless
owner. CMS preserves workspace authorization and passes those facts downward.
Engine permits this authority only for preparation, not participant activation.
It never imports or calls CMS or CTF. The inactive account is not enabled, and
its management-user fence is not made an active-user authorization.

Event authority also fences model demand, event start/end, spin-up lead time,
and cleanup delay. Organizer updates invalidate the captured revision and
revoke dependent pending grants in the same event-update transaction. Admission
cannot accept an earlier demand/window projection after such a mutation.

Warm preparation uses the existing unclaimed, unexpired generation ledger and
its own `engine:warm-generation` authority. Management checks the inactive,
passwordless owner under lock; CMS also checks the managed warm identity and
workspace. Ordinary inactive users cannot acquire this preparation authority.
Claiming, retiring, deleting, or changing captured ledger facts invalidates it.
The normal provisioning-to-ready transition preserves preparation authority.
Claim revokes preparation grants before CMS replaces the launch inputs; fresh
claimant admission and activation remain inside that same transaction. Failure
rolls back the claim, ownership transfer, and revocation together.

Consumption, removal, membership changes and owner mutations revoke dependent
pending grants transactionally. A handoff does not transfer preparation
authority to a participant. Warm activation reauthorizes the claimant and
commits claim, ownership, allocation and activation intent together. Resume
uses the existing native `range resume` executor and operation generation while
obtaining a fresh grant epoch. A bounded admission denial rolls both Engine and
CMS back to paused instead of leaving a split lifecycle state.

Ordinary Range status changes advance selector freshness without revoking model
grants. Launch authorization uses a generation-stable `engine:model-launch`
fence, while owner, workspace, destruction and deletion changes still revoke
that range's authority. Consequently provisioning-to-ready cannot revoke its
own grant or a sibling grant that happens to share a user or workspace.

All local and remote launches use the durable provisioner-launch outbox. Local
mode registers the canonical launcher worker with `transaction.on_commit`, so
the subprocess cannot observe a Range, operation input, preparation, allocation,
or intent before the outer transaction commits. Rollback starts no subprocess;
normal outbox retry and generation fencing remain authoritative after commit.

Release targets the original allocation and operation, not a reusable draw key.
It keeps original provider/account references and tombstones, retains unresolved
liabilities, and preserves shared/event commitments until their windows expire.
The existing capacity reconciler handles revoked, expired, failed and destroyed
allocations. Late cleanup cannot release a successor.

## Verification boundary

The allocation suites cover real PostgreSQL contention, duplicate launches,
shared first use, independent pools and freshness after lock waits. Integration
tests cover atomic outbox rollback, warm claims, resume, explicit spare authority,
provider-pool restrictions, snapshot-bound refresh, optional absence and
installer/runtime schema parity. These are local and synthetic results, not
live provider, broker or billing qualification.
