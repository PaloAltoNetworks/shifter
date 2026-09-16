# Model-access operations design

Status: proposed for [#681](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/index.md),
ADR-061, 2026-09-06. Procedures describe implementation requirements.
Management endpoints and operational commands must be delivered and tested
by the [owning issues](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/delivery.md) before use.
No live provider, load, revoke, migration or restore evidence is asserted here.

## Deployment and responsibility

Run a dedicated broker Deployment in the existing Shifter Helm release,
using a separate service account, private TLS service and bounded resource
requests/limits. Start qualification with two replicas on separate nodes
where available, a disruption budget, graceful draining and pinned images.
Use the existing Cloud SQL/PostgreSQL, Engine worker, GKE monitoring/logging,
shared audit and deployment pipeline. Do not introduce a Redis authority,
gateway database, service mesh, per-range model project or new queue service.

| Owner | Operational responsibility |
| --- | --- |
| Deployment/cloud operator | Billing/model enablement, approved project/account inventory, IAM, egress, TLS, quota requests and emergency shard identity disable. |
| Platform operator | Catalog and price review, account ceilings, broker rollout, status, revoke/re-enroll, reconciliation, support and recovery. |
| Event organizer | Accurate cohort/spare demand and event window, delegated model profile, event budget, participant communications and authorized event access suspension. |
| Scenario maintainer | Pinned client/protocol/artifact compatibility, required/optional model behavior and useful participant acceptance. |
| Release/security owner | Independent IAM/network/adverse-case evidence, documented operating envelope, exceptions and release decision. |

Configuration flows from installation validation through Terraform outputs,
runtime rendering, settings/env manifest and chart values. Secrets use exact
references and workload identity; a setup script must not become a second
catalog. Register the new production process in path ownership, test/security
CI routing, SBOM/image provenance and import checks. Keep the exact
provisioner-Job admission shape intact.

Readiness checks configuration/schema, supported adapter versions, control
authentication and accounting reachability; it does not send a paid prompt.
Liveness checks process health without depending on provider availability.
An authenticated, rate-limited synthetic probe has its own small operator
budget and fixed harmless prompt. It exercises the real data path before a
cohort is enabled. Its result cannot make an unauthorized range grant active.

TLS uses a deployment-approved CA or publicly trusted certificate for the
private hostname, automated renewal and overlap. Guests verify the hostname
and chain from their qualified image. Never disable verification. Monitor
certificate expiry and test rotation with active streams. The GCP private
load balancer must preserve the source identity required by the security
design; rendered manifests alone do not prove this.

## Objectives and capacity envelope

These are initial release acceptance targets to measure, not current SLOs:

| Dimension | Proposed target and measurement |
| --- | --- |
| Broker/control availability | 99.9% over the declared event window for valid, within-budget requests, measured separately from upstream availability and policy denials. |
| Added admission latency | p95 at most 250 ms and p99 at most 1 s within one deployment region, excluding provider generation; record cohort size and database contention. |
| Revocation | New admission denied after the Engine commit; downstream delivery and upstream transport stopped within 10 s. Measure last byte and dispatch attempts, including control-service loss. |
| Request bounds | Default total 120 s, connect 5 s, stream idle 30 s, control timeout 2 s and continuation checks at most 5 s apart. A profile may tighten these; larger bounds require measured qualification and revised maximum charge. |
| Payload and process bounds | Initial 1 MiB decompressed JSON request, 32 KiB headers, 1 MiB maximum SSE event and 256 KiB streaming buffer per connection; reject excess. Pin depth/field-count/response limits in the adapter contract and test the selected client's useful context. |
| Reconciliation | Expired dispatch/settlement leases discovered within 60 s; unknown charges remain reserved or conservatively spent, never automatically refunded. |
| Recovery | Restore exercise target: accounting RPO at most 5 min and admission recovery within 60 min after database availability, with mandatory fencing and reconciliation. Older restored state cannot simply regain remaining budget. |

Sizing inputs are measured active ranges, concurrent requests per range,
request arrival rate, output rate, mean/p95 duration, token upper bounds,
provider pool limits, broker CPU/memory and Engine/DB request latency. For
`N` active ranges with at most `C` connections each, test at least `N*C`
broker transports and the corresponding reserve/settle plus continuation
traffic (up to `N*C/5` continuation checks per second at full utilization).
Admission and pool row contention can be the first limit; adding broker
replicas does not increase provider quota or remove database serialization.

Size against effective sharing pools as well as range counts. Test one large
all-ranges pool, many individual pools and overlapping group/event/user
bindings. Shared capacity is committed once with child draws; dedicated
reservations still add against real provider quota. A common budget row can
become the contention limit. Exercise bounded selector pagination, dynamic
membership bursts and synchronous revision fencing before background
reassessment; do not qualify only fixed event-sized snapshots.

Use bounded tests at the declared cohort and a controlled overload case.
Report the maximum sustainable cohort from evidence. The design makes no
200-desktop guarantee. HPA may respond to active streams and resource usage
within operator limits; scale-down drains connections for the request bound
and then terminates them with retained accounting. There is no transparent
stream migration or post-crash replay.

## Scenario model needs and required-access admission (M02, #2119)

A scenario declares its logical model need through a Shifter-owned, staff-authored
overlay (`ScenarioModelNeeds`), not by editing the RAES pack and not through the
deploy-time mounted catalog. Author it per registered scenario pack:

- Key it by `scenario_id` and set `authored_package_digest` to the exact pack
  content digest the need is authored against. Map each `workload_role` to a
  `ScenarioNeed` (required flag, required/allowed capabilities, allowed
  strategies, data regions, limits) whose `profile_id` names a profile in the
  mounted catalog. The overlay is validated on save; a workload-role/key or
  digest mismatch is rejected.
- Because the overlay rides the runtime pack lifecycle, adding a model-requiring
  pack needs no catalog redeploy. But re-registering the pack with new content
  changes its digest: re-author the overlay against the new digest, or a
  required launch fails closed (`digest_mismatch`) until you do.

Organizers declare typed model demand per workload on the event (CTF-908):
expected concurrency and per-participant request/input/output demand plus the
allowed strategy. This is capacity/sizing input constrained by the scenario
need; it cannot name a provider, account, region, shard, credential, or price.

Required-access failure is deliberate and visible. A launch of a scenario with a
required model need is refused before any range is dispatched, across every
launch family (participant, spare, wave, standalone, recovery-rebuild, and
warm-claim activation), when: model access is unconfigured, the referenced
profile is absent, the pack digest is stale, a required capability is
unavailable, the profile intersection is empty, the sharing overlap conflicts,
or the range posture is zero-egress (`deny-all`/`none`) for required external
model use. An unavailable sharing authority yields an indeterminate outcome that
also refuses the launch (fail closed) rather than proceeding. Optional model
access that cannot be satisfied is admitted as an explicit visible absence and
does not block. The refusal carries a bounded reason code and no raw figures or
rejected values. The admitted private-broker exception for a zero-egress range
is deferred with the broker runtime.

## Cost and quota controls

Before an event, inventory provider model enablement, supported regions,
quota-pool dimensions, observed usage/freshness, expected input/output rates,
shard weights, capacity reservations and reviewed price validity. Test one
approved call per configured alias/project. Distinguish published limits,
observed limits, deployment caps and unobservable/dynamic capacity. Quota
values and model access are deployment prerequisites, not universal defaults;
see [Google's current quota guidance](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/quotas).

Event maximum authorized model cost is the sum of permitted request upper
bounds, capped by all parent budget accounts. Actual provider invoices may
include tariff changes, taxes, infrastructure and non-broker use. Budget
alerts are useful independent detection, not hard admission. Enable provider
billing alerts at operator-chosen thresholds and reconcile bounded aggregate
usage against local accounting without exporting prompt bodies.

Budget for two broker replicas, internal load balancing, DNS/TLS, metrics/log
retention, PostgreSQL I/O/storage, network/NAT egress, token issuance, optional
provider committed throughput and inference/tool charges. Avoid quoting a
fixed monthly price without deployment quantities and current tariffs.
Cross-project sharding has IAM and quota administration cost; separate keys
do not buy additional quota. Reuse the existing deployment's infrastructure
until measured load requires a reviewed change.

## Sharing-pool operation

Before publishing a binding, preview its selected ranges, snapshot/dynamic
mode, independently shared facets, overlapping accounts, priority conflicts
and active-range effect. Confirm authority across every included event or
group. All-ranges means one deployment, not all customers. Empty collections
must never expand into all ranges. Show shared-only pool exhaustion risk and
offer per-range limits; do not silently partition a pool equally.

Changing a selector or routing revision preserves stable financial accounts,
spent/reserved balances and original request liabilities. Publish with a
revision comparison and fresh membership/authority checks. Revoke the old
affected grant revision before reassessment; dynamic additions receive access
only after admission. Monitor membership freshness, conflicts, invalidation
lag, common-account contention and orphaned draw references without exposing
group rosters in global telemetry.

Drain a pool by stopping new admissions and fencing member grants, then wait
for active transports and unresolved provider outcomes under the ordinary
reconciliation rules. Cleanup retains tombstones and original account vectors;
deleting a group or binding cannot refund spent/unknown charges. Show which
other bindings still reference the pool before changing provider identity.
Revoking one range should leave its neighbors usable; disabling a shared
provider identity is a separate, explicitly wider emergency action.

Restore qualification includes overlapping bindings, pinned shared assignments,
membership revisions and unknown requests charged to old pools. Reconstruct
authority before enabling admission; never recover balances by summing
overlapping constraint accounts as if each were a separate provider invoice.
See the [sharing contract](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/sharing.md)
for the selector and allocation rules.

## Observability and retention

Expose bounded metrics for admissions/denials by reason, active transports,
reserved/spent units, unknown charges, lease age, revocation latency,
allocation skew, provider throttles, price/observation age, refresh failures,
control latency, audit backlog and cleanup residuals. Use bounded catalog
IDs for metric labels; range/subject/request IDs belong in access-controlled
audit/search records, not high-cardinality metrics. Prompts, responses, tool
arguments, tokens and raw provider errors are forbidden in all telemetry.

Engine commits decision and accounting audit intent before dispatch. If that
durable write fails, deny the call. External audit archival failure may
continue only while the existing durable outbox is healthy and within its
operator-set backlog bound; alert on lag and stop new model admission when
that bound is exceeded. Do not create a broker-local best-effort audit store.

Initial deployment defaults: retain credential hashes only until expiry plus
24 hours for bounded abuse investigation; keyed retry fingerprints/request
detail for 24 hours after settlement; body-free accounting/audit and evidence
for 90 days unless the deployment's approved policy requires otherwise.
Never expire unresolved charges, cleanup references or obligations merely
because the normal retention period elapsed. Aggregate retained costs before
deleting individual detail. Restrict exports to authorized operators; log
their access. Document and test backup retention and deletion separately.

## Rollout and legacy migration

1. **Inventory:** identify all live range generations, stored full Vertex
   secret/key references, shared-key source consumers, AWS role consumers,
   model projects and effective IAM. Inventory metadata/references only;
   do not copy credential values into reports. Reconcile #1446 with the
   selected scenario so a new guest-key path is not introduced in parallel.
2. **Expand disabled:** ship additive Engine schema, policy catalog, broker,
   identity/egress and operation projection behind deployment configuration.
   Existing ranges continue their recorded path. No new model grant is issued
   until the broker prerequisites and strict admission checks pass.
3. **Validate:** run synthetic transport/accounting tests, effective IAM and
   root-context network negatives, token rotation/revoke and no-body leakage
   tests on disposable ranges. #2083's secret creation boundary must be
   proven for any remaining bootstrap/legacy-secret operations.
4. **Canary:** create a fresh GCE range from the selected released image and
   scenario. Bootstrap broker-only client access, prove useful tool/model
   interaction, then pause/reset/revoke/destroy and independently inventory
   residuals. Charge probes to a separate bounded qualification account.
5. **Bounded cohort:** explicitly enable the approved event/profile and
   measured range limit. Compare local reserved/used totals to provider
   observations, exercise overload and failure, and publish sanitized evidence.
6. **Drain legacy:** move participants through fresh admitted generations;
   do not silently replace credentials in running guests. Coordinate shared
   GSA revocation across every consumer. Remove dynamic Vertex key creation
   and host secret-reader grants from the broker path; preserve original
   reference deletion until every old generation is retired.
7. **Contract:** after no live legacy references and no effective legacy
   invocation, remove obsolete config and grants under the migration issue.
   #681's GCP readiness cannot rely on a disabled secret with a still-working
   previously minted provider token. Test that token's denial and record the
   measured window. AWS legacy cleanup remains independently scoped.

Do not rename a proposed ADR into a claim that live migration is complete.
Keep operator-visible `legacy`, `broker-canary`, `broker-qualified`,
`unavailable` and `cleanup-pending` deployment evidence/projections without
inventing new range lifecycle states.

## Failure and incident procedures

| Trigger | Immediate action | Recovery/evidence |
| --- | --- | --- |
| Provider 429/503 or quota exhausted | Stop admission to an unhealthy shard according to policy; return safe retry guidance. | Reassess fresh quota/health; explicitly reallocate only within approved model/region/price policy. No blind retry or cross-cloud fallback. |
| Engine/PostgreSQL unavailable | Reject new calls and refresh; terminate streams when continuation lease expires. | Recover service and reconcile unknown dispatch/settlement before new grants. |
| Broker process/node loss | Connection fails; keep request reservation and unknown outcome. | Replacement replica serves new admitted requests, not replay of the lost request; reconcile original provider reference. |
| Suspected participant-token theft | Revoke its grant epoch, fence streams and re-enroll after current authority checks. | Prove old token fails from its original subnet and another range; inspect body-free usage. |
| Suspected broker/provider identity compromise | Disable admission and drain the affected shards; deployment operator disables provider identity/permissions. | Measure effective denial with a pre-existing token, rotate/rebuild, reconcile spend and assess the entire affected shard inventory. |
| Budget/price mismatch or unknown billable feature | Disable that alias/feature and retain conservative reservations. | Review prices/usage adapter, publish a new revision and rerun billing-bound tests. |
| Secret/identity API outage | Fail new credential-dependent effects; no same-project/shared-key fallback. | Restore prerequisites; clean up by original references and re-enroll only through authoritative services. |
| Audit backlog exceeds bound | Stop new model admission and page operator. | Restore protected sink, verify durable backlog drains, then resume. |
| Slow clients or overload | Enforce request/concurrency/idle limits and bounded buffers; reject excess work. | Measure pressure and scale only within the qualified provider/database envelope. |

Rollback first disables new grants and drains admitted requests. Keep the
expanded schema/readers and cleanup compatibility until all new references
can be handled by the previous version. Roll back images/config only to a
version that understands live grants, request records and cleanup obligations.
If no compatible version exists, keep model access disabled and repair the
forward release. Never restore direct guest credentials as a recovery step.

For database restore, hold the broker and enrollment route disabled before
the restored application starts. Rotate a deployment-level admission epoch
outside the restored database using the existing deployment secret/config
authority, invalidate every restored grant, and conservatively freeze affected
budgets. Reconcile the backup's request/accounting cutoff with protected audit
and provider observations. Unknown missing charges consume remaining budget
until an authorized conservative adjustment is recorded. Fresh enrollment
uses the new admission epoch; old guest tokens cannot regain authority.

## Qualification evidence

The release bundle records repository/image/pack/client/SDK/chart digests,
configuration and policy/price revisions, provider/project/region references
under protected access, measured cohort/limits, effective IAM/network probe
results, allocation/rate/spend contention results, first/last stream timestamps
around revoke, cancellation/unknown-cost disposition, cleanup inventory and
restore results. It contains no credential or prompt payload.

Prove useful participant model/tool use, multiple GCP projects and aliases,
budget exhaustion, stale generation, wrong subject, expired grant, token
refresh, worker loss, denied management/peer/metadata access, unavailable
dependencies, price expiry, event stop and full teardown. Positive controls
must show that allowed operations worked before negative results are credited.
Independent provider readback is required; a script's success exit or a mock
is not cloud evidence. Feed the qualified GCP slice to #2091 and keep each
future provider/tool profile's evidence separate.
