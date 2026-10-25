# Quota allocation and pending grant preflight — #2120 / M03

Inspected baseline: `5fbf929df82717164ed027c01f8ed355b95c0929`.
Requirement: PLAT-202. This note applies ADR-047, ADR-043, and
[ADR-060](../../adr/060-model-access-allocation-accounting.md) to the current
repository. It is design guidance, not an implementation plan or runtime proof.
The [architecture](architecture.md), [sharing contract](sharing.md), and
[security design](security.md) remain authoritative.

## Decision and current gaps

M03 belongs in Engine's existing admission, capacity, sharing and launch-intent
boundaries. M19/M20 already supply membership projections and authority fences;
consume and extend them only where necessary, without a parallel authority store. Commit the complete allocation, capacity effects, non-usable pending
grant, immutable operation input and dispatch intent atomically. An admission
preview, deterministic ranking, or pending grant alone cannot authorize use.
Required-model denial must leave no dispatchable intent or partial alias draw.

The following are concrete gaps in the inspected code, not assurances supplied
by its module comments:

| Incumbent | Consequence for M03 |
| --- | --- |
| `engine/services/_capacity_plan.py` and `_capacity_plan_persistence._committed_reservation()` observe outside their local transaction, then aggregate reservations without a shared mutex. | `atomic()` and a sum do not serialize concurrent first reservations. Lock a durable identity for the real provider quota before checking overlapping commitments, including when no reservations exist. The caller must also be outside any outer transaction during observation. |
| `_capacity_admit._draw_one()` books metrics individually; `_book()` catches every `IntegrityError` as an already-booked draw. | Do not inherit partial multi-metric success or treat a ceiling/check violation as idempotent success. Roll back the complete model effect vector; only a verified matching persisted allocation proves replay. |
| `release_range_capacity()` locks draws before updating reservations; admission locks reservations first. Release selects every open row by draw key. | Define a compatible lock order across admit/release/expiry/reconcile and scope model cleanup to its original allocation/generation. Blind reuse can deadlock or release a successor using the same stable draw key. |
| `cms/services/_model_admission.assert_launch_model_access()` passes `demands={}` and can use the launcher as a fallback subject; Engine returns only recomputed verdicts. | Thread the CTF-owned declaration, actual admitted owner/draw and scenario revision through the existing launch seam. Launcher, owner, range and pre-creation draw are different identities. A missing required demand/authority is not an empty permissive declaration. Define a typed non-event scope for standalone and warm demand rather than fabricating a CTF event. |
| `preview_effective_policy()` explicitly supplies no authority. `_sharing_resolution` can omit a match when projection/subject evidence is missing or revoked; `_model_admission._fold_sharing()` treats no contributions as no restriction. | A locked allocation must distinguish proven non-membership from unavailable evidence and revoked subject authority. Never turn missing/revoked applicable evidence into private/default admission. Check subject authorization even when there is no sharing binding. Reuse the compiler; strengthen its authoritative input boundary rather than adding a second evaluator. |
| `get_or_create_allocation_group()` persists a UUID but no assignment or first-use mutex protocol. | Lock the canonical group before first assignment and persist the alias assignment. A stable rendezvous seed does not pin a result against catalog, eligibility or capacity changes. |

## Transaction, identity and accounting guardrails

**One durable launch decision.** Use `engine.launch_intents`' generation owner,
`ProvisionerLaunchIntent`, `OperationInput`, and `engine.operation_inputs`.
`enqueue_provisioner_launch()` already commits input and intent together and
checks replay intent equivalence. Model effects must join that atomic boundary,
not run after enqueue or only in `transaction.on_commit`. Persist the complete
decision before any worker can see dispatch. Where CMS has already reserved a
range/workspace slot, preserve its existing rejection cleanup and retain an
Engine reconciliation obligation for any separately committed reservation.

Keep `request_id`, stable participant/spare draw key, canonical range UUID,
existing operation/generation fence, per-alias allocation group, and grant epoch
separate. `Range.provisioner_operation_id` can rotate for lifecycle commands:
cleanup must retain the original access binding and distinguish it from the
current destroy/pause operation. Do not mint a second execution generation.
Resume without a new range still requires a fresh grant epoch; revoked/expired
grants are terminal. Warm prepare is system-owned and has no usable participant
grant; activation binds the actual claimant through the existing claim service.

**A complete immutable snapshot.** Retain deployment, workload/capability set,
owner/event or other typed scope, scenario/package digest, catalog and effective
policy digests, price revisions, effective strategy, full alias-to-shard map,
original provider/identity references, assessments/draws, deadline, binding and
pool routing revisions, and membership/subject/publisher/spending fence vectors.
Persist normalized shared DTOs, not caller-owned mutable mappings. The existing
`AccessGrant` DTO is a wire contract, not a Django model, credential, or proof
of activation. Extend canonical contracts only for genuinely missing information.
Protect referenced revisions and liabilities from cascading deletion; existing
capacity and binding models have cascading relations and do not establish that
retention invariant for new dependents.

Replay returns the recorded map without re-ranking against today's catalog.
Same request/generation with different semantic intent conflicts. Current
authorization, expiry and withdrawal still gate use: immutable routing does not
freeze authorization. A catalog rollout may stop new admission until bindings
are republished; it must not rewrite old snapshots or reinterpret original
cleanup references. Removed shards remain identifiable for cleanup only.

**Shared quota is a physical identity.** Build on `QuotaPool`, its canonical
real-quota uniqueness validation, `shared.capacity` assessments, and Engine's
reservation/draw ledger. Across catalog revisions, different names for the same
real provider quota must not create independent headroom. Compute partition,
model account/project, credential identity, sharing pool, capacity commitment
and monetary account remain distinct. A deployment-local reservation cannot
claim exclusivity over quota consumed by other deployments or external clients;
retain observation timestamps, provenance, dimensions, units and conservative
policy bounds. Unknown health, stale required observations or unsupported
dimensions yield non-admission, never synthetic observed capacity.

Shared capacity commits once per metric/window; event/range draws consume that
parent without re-reserving it. Deduplicate selector/account references, but sum
distinct alias demands against a common quota, and count independent parent
commitments. Use explicit UTC half-open windows and freshness checks at the
commit decision, including time spent waiting for locks. Reject invalid units,
windows, negative/non-finite quantities and overflow. Monetary values and token
counts use exact bounded integers; `CapacityReservation`'s floats are not money.
Capacity reservation is not per-request spend/rate accounting.

**A consistent lock protocol.** Extend the existing owner-first transaction
boundary and sharing publication order: publication/refresh lock membership
projection before its authority fences (see the real PostgreSQL sharing tests).
Do not blindly implement the older prose as fences-before-projection. Include
binding/pool publication and first-group creation in the ordering analysis;
lock candidate quota identities in canonical order independent of rendezvous
rank, and use the same order for release, migration and reconciliation. A lock
on an empty reservation query is insufficient. Concurrent publication of a
newly applicable binding must be serialized or detected too; locking only
previously matching rows leaves a phantom-policy gap. Use existing owner/fence
revisions for this boundary, with bounded revalidation, rather than a global
deployment allocation lock or a new general locking framework.

Database uniqueness/check constraints backstop identity, closed persisted
states, positive revisions, nonnegative balances and ceilings. They supplement
shared semantic validation, not replace it. A retryable database conflict must
roll back all effects before bounded retry through existing workflow machinery;
never catch arbitrary database errors inside a broken transaction and proceed.

**Release is not refund.** Reject/abort, spare expiry, claim/activation failure,
reset/replacement, pause/resume, owner transfer and late results must all use
existing lifecycle/applier/reconciliation paths. Fence old authority before
re-admission. Release only the original member draw; do not release a shared
parent while other members or unresolved liabilities depend on it. Neither
event expiry nor VM deletion proves provider work stopped. Preserve original
spend/account identity, unknown liabilities and tombstones across pool migration
and routing changes. A pending, never-used grant can be cancelled without
pretending that an active grant's uncertain charge was refunded.

## Cross-cutting boundary map

Paths below are relative to `shifter/shifter_platform` unless prefixed otherwise.

| Layer and canonical incumbents | Required passage through the boundary |
| --- | --- |
| Authenticated event/scenario inputs: `ctf.services.authorization`, `ctf/services/range/capacity.py`, `cms/scenarios/model_needs.py`, `cms/services/_raes_range_create.py`, Workspaces public authorization services | Preserve actor/event/workspace authorization, digest-bound `ScenarioModelNeeds`, and server-derived owner/draw references. Organizer input remains logical bounded `EventModelDemand`; it cannot select provider accounts, secrets, URLs or prices. All cold, spare, replacement, standalone and warm launch families pass the same enforcing Engine gate. |
| Closed contracts: `shared.model_access` catalog/digest/admission/policy/effective-policy/allocation/authority/provider modules | Reuse canonical strict types, bounded `ContractError` codes, duplicate-key-rejecting raw parser, normalization, digests and M01 vectors. Do not fork a serializer schema, policy evaluator, exception tree or `shared.schemas.SpecBase`. Pydantic validation errors must be translated without rejected values. Match actual `ModelAdmissionOutcome` enum values; older prose uses “rejected” where M02's DTO uses `denied`. |
| Authority persistence: `_sharing*`, `config.model_access_sharing`, `config.model_access_authority`, `shared.model_access.authority_port` | Recheck complete, fresh, allowed evidence under locks. Snapshot inclusion does not freeze authorization; membership does not imply publisher or funded eligibility. Owners invalidate transactionally through CTF → CMS → Engine or the existing neutral port. Missing adapters/evidence deny; Engine never calls back into owners. |
| Installation and env shapes: `shifter/installation/loader.py`, `model_access.py`, generated `published_contract/model-access-policy.v1.schema.json`, `render.py`, `runtime_inventory*.py`; `shared.model_access.runtime`, `config._model_access_settings` | Root YAML duplicate/merge-key rejection, generated-schema parity, canonical semantic validation and bounded mounted-catalog digest checks remain mandatory. Use shared `settings.model_access`, not backend-specific copies. Runtime env carries only enabled/path/digest; distinguish a disabled feature from a missing enforcing policy. Any new catalog field must pass independent installer and runtime consumers. |
| Host/deployment surfaces: `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/aws_eks.py`, `shifter/installation/gcp_model_broker.py`, `platform/charts/shifter/templates/model-{broker,broker-network,access-control}.yaml`, `shared.cloud.sensitive_env` | Retain runtime inventory allowlists, literal-versus-secret reference shapes, broker-only identity inventory, fixed mount paths and ConfigMap size checks (the deployment package's 96 KiB bound is tighter than the runtime parser's 2 MiB limit). No credential values or catalog bodies in process argv/env, Job commands, setup logs, Terraform state or images. Generic sensitive-env splitting does not authorize delivering provider credentials to guests. M03 needs no credential hydration. |
| Dispatch and results: `engine.launch_intents`, `engine.operation_inputs`, `shared.operation_envelope`, `shared.raes.operation_input`, `engine/services/_operation_apply*`, `engine.retry_binding`, `engine/services/_cleanup_verification.py` | Keep command allowlists, immutable input digest/replay checks, domain payload validation, current-generation authorization and authoritative inbox/applier. Add only the admitted non-secret projection needed by a consumer; do not smuggle extra fields through free-form JSON or give the provisioner Engine-table ownership. Result/cleanup replay cannot change a successor. |
| Network/provider seam: `shared.model_access.network`, `shifter/installation/range_egress.py`, `shifter/engine/provisioner/gcp_range_cell_model_broker.py` and range-cell firewall validation | Allocation does not admit a network exception. Required external access under zero-egress remains denied until the explicit private-broker capability is admitted through the existing contract. No generic proxy, participant endpoint selection, direct-credential fallback or inference of model provider from compute backend. Broker IAM, TLS/source binding and enrollment remain separate qualification gates. |
| Errors/audit/telemetry: `shared.errors`, `shared.api.errors`, `cms.exceptions.CMSError`, existing sharing errors, `shared.audit`, `shared.log_sanitize`, `config.logging`, existing metrics transports/patterns in `config.capacity_metrics*` | Preserve public error envelopes and bounded codes. Sanitation of newlines is not secret redaction; arbitrary `details` strings and chained `logger.exception` output can leak values. Emit authored reasons and safe correlations only, with no raw provider/Pydantic/SQL errors, prompts, credential references or account topology. Commit body-free security audit via the existing strict audit path; extend its vocabulary normally. Measure admission/denial, contention, stale observations and reconciliation lag with bounded labels in an appropriate model-access namespace, not per-user/range labels, portal saturation gauges or a second telemetry stack. |

## Extensibility and verification boundaries

The existing seams already allow the next provider, model alias and affinity:
parameterize allocation by validated adapter ID, real quota identity/dimension,
versioned strategy, per-alias affinity and typed scope. Use the provider registry
and closed observation/result contracts; do not use the compute
`BackendCapability` or `shared.cloud._get_provider()` as a model registry.
Event strategy must be permitted by both the scenario/effective profile and the
deployment alias contract; make the selected strategy explicit and persist it.
Do not silently ignore `EventModelDemand.allowed_strategy` or override a pinned
shared assignment. Incompatible new members reject; they do not reshuffle the
group or get an unrecorded private alternate.

Behavioral evidence must use the existing PostgreSQL lane (`make
test-platform-postgres`, `pytest.mark.postgres`, transactional tests), following
`tests/engine/services/test_model_access_authority_postgres.py`. Cover concurrent
first use of shared versus independent pools, overlapping and adjacent windows,
multi-alias rollback, stale observations after lock waits, duplicate and changed
intent, authority removal/new binding publication, failed strict audit, launch
crash boundaries, and late release after replacement. Reuse M01 golden vectors,
schema-publication parity tests, M02 launch-family tests, and warm-pool/result
replay tests. SQLite or mocked locks cannot establish concurrency guarantees.

Repository constraints in scope are `.ground-control.yaml`, `.importlinter`,
`scripts/check_layer_imports/layer_imports.yaml`, ADR registry/exceptions,
`.pre-commit-config.yaml`, `.github/quality-path-filters.yaml`, and the root
Makefile. Run ADR CI checks and platform import checks; touched installer,
provisioner, chart, workflow or Terraform surfaces retain their native lanes.
Local tests do not qualify live provider quota, revocation or broker networking.

M03 does not implement a broker, provider SDK calls in admission transactions,
credential issuance/enrollment, streaming request settlement, live qualification,
new public endpoints, a scheduler, a second range lifecycle, automatic failover,
or operator fan-out scripts. It leaves compute advisory semantics intact and
keeps model activation disabled until its separate runtime gates are satisfied.
