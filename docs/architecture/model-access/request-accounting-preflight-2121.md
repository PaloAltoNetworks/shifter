# Request accounting and dispatch lease preflight — #2121 / M04

Inspected baseline: `78deb0f911c1a2199a2124835a1dd2a9d75fa55e`.
Requirement: PLAT-202. This note applies
[ADR-060](../../adr/060-model-access-allocation-accounting.md) and
[ADR-061](../../adr/061-model-access-operations-qualification.md) to the
current repository. It is design guidance, not an implementation plan or
runtime proof. The [architecture](architecture.md),
[allocation contract](allocations.md), [sharing contract](sharing.md),
[security design](security.md), and [operations design](../../ops/model-access.md)
remain authoritative.

## Decision and blocking contract gap

M04 belongs in Engine's existing allocation, authority, audit, lifecycle and
reconciliation boundaries. Reserve every applicable account atomically before
provider effects, persist one dispatch attempt and its short lease, settle
verified usage once, and retain the conservative hold when execution is
ambiguous. The independently packaged broker must consume this authority later;
it must not own Django persistence, recompute policy, or keep authoritative
balances in process memory.

The current repository has one material contract gap that must be closed before
any configured budget account can authorize a request. `SharingPool` and the
effective policy carry opaque spend, rate and concurrency account references,
but neither catalog version defines what those references mean. There is no
canonical account dimension, unit/currency, ceiling, UTC window, revision or
authority source. `EventModelDemand` is capacity demand, not monetary policy,
and `AccessLimits` is a request/grant envelope rather than an implicit
definition of every parent account. Inferring policy from account names or from
the scope that referenced them would make the ledger non-auditable.

Add one closed, versioned account-definition contract under
`shared.model_access` before M04 enables an account reference. Evolve the
published catalog to a new version rather than changing v1/v2 semantics or
digests. Every referenced account must resolve during publication and runtime
validation to a stable reference, dimension and unit, currency where relevant,
ceiling, explicit UTC window semantics, revision, and server-owned authority
source. Dynamic event and standalone-owner accounts need a typed server-owned
policy/default projection; do not overload the participant-authored demand
JSON. Missing definitions, dimension/currency mismatches, expired revisions,
unsupported windows, unknown billing features, and unbounded requests fail
closed.

## Reuse and ownership boundaries

| Canonical incumbent | Required M04 use |
| --- | --- |
| `shared.model_access` closed models, catalog parser/digests, `AccessLimits`, `PriceSchedule`, `BillingComponent`, `BillingBound`, `ProviderUsage`, `VerifiedUsage`, `CancellationResult`, and `ContractError` | Extend these contracts for the missing account definition and request-accounting DTOs. Do not introduce provider dictionaries, a second schema/parser, or another exception hierarchy. Preserve duplicate-key rejection and bounded code/path errors that omit rejected values. |
| `shared.model_access.effective_policy.compile_effective_policy()` and Engine's sharing-authority services | Consume the already deduplicated spend/rate/concurrency reference sets and locked authority revision vector. Do not re-evaluate selectors in the broker or implement a second precedence algorithm. |
| `ModelAllocation`, its immutable catalog/effective-policy/price snapshot, `ModelAllocationAuthority`, `ModelPendingGrant`, and the allocation lifecycle services | Bind requests to the exact allocation generation, alias map, account set, prices, authority revisions and grant epoch. Current policy authorizes new work; the original snapshot and postings remain accounting truth after revocation or membership changes. A pending grant remains unusable. |
| `engine.retry_binding` and `shared.operation_intent` | Reuse their PostgreSQL uniqueness/savepoint arbitration pattern for scoped idempotency. Their public unkeyed operation digest is not suitable for prompt-derived fingerprints. |
| `ctf.models.communication` and `ctf.services.communication.delivery` | Reuse the token/expiry/fence and stale-worker settlement pattern, not its at-least-once delivery semantics. A model dispatch is never automatically reclaimable after possible provider I/O. |
| `shared.audit` (`AuditEvent`, strict writer and `AuditLog` chain) | Add specific request/accounting actions and entity types through the existing vocabulary. Commit the body-free decision audit in the same transaction before dispatch. Use the integer request-row identity plus safe `entity_ref`/request correlation; do not place prompt-derived values in audit fields. Acquire the audit-chain lock last. |
| `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, and `config.logging` | Return authored stable codes through the existing safe envelope. Never reflect provider, Pydantic, SQL or fingerprint values. Newline sanitation is not secret redaction. Existing ECS logging drops unknown labels, so do not claim model metrics exist merely because an `extra` mapping was logged. |
| `cms.management.commands.reconcile_range_events`, the worker-reconciler deployment, and the public `engine.services` facade | Add a bounded, failure-isolated accounting pass to the existing scheduled reconciliation process. Do not add another daemon, queue, or direct CMS access to Engine models. The existing unwired allocation reconciler is a helper, not proof of operation. |
| Existing provider-neutral metrics publisher patterns in communication, warm-pool and capacity services | Use a bounded-cardinality model-access namespace when M04 needs operational counters. Do not use user/range/account IDs as labels or create a second telemetry transport. Broader operator telemetry and external usage readback remain M12. |

## Ledger, state and transaction guardrails

Keep these concepts separate in both contracts and persistence:

- an immutable account definition and revision;
- one durable account/window balance identity;
- a request reservation bound to the allocation, account set, price vector,
  grant epoch and semantic intent version;
- one posting/hold for each distinct applicable account, locked and charged
  once even when multiple selectors found it;
- one canonical request cost for provider-cost reporting, which is not the sum
  of overlapping account postings;
- dispatch and continuation lease/fence state; and
- a durable reconciliation obligation for unresolved outcomes.

`ModelAllocation.unresolved_liabilities` is a derived lifecycle fence, not a
monetary source of truth. Distinct caps all constrain a request, while a shared
pool reached through two selectors is debited once. Budget reductions can make
an account over limit and block new work; they cannot erase spent, reserved or
unknown amounts. A database constraint therefore must not require the mutable
ceiling to remain above already committed value.

Use bounded integers for requests, tokens and money. Compute each enabled
billing component from the allocation's immutable price revision with checked
integer ceil division of `units * price` by `denominator`, while guarding
multiplication and aggregate overflow. Never settle old work against the current
catalog. Unknown features, expired prices, unsupported bounds, negative values,
unit/currency mismatch, or a missing component reject before reservation.

Extend the existing owner-first lock protocol consistently across reserve,
dispatch, settlement, revocation and reconciliation:

1. range and execution generation;
2. allocation and grant epoch;
3. sharing membership/publication/fence state in the order already enforced by
   the sharing-authority PostgreSQL tests;
4. every account/window identity in stable canonical order; and
5. the request row, with the strict audit-chain lock acquired last.

Lock a durable account/window identity even when it has no postings; selecting
an empty set does not serialize concurrent first use. Back the identities and
state transitions with uniqueness and checks for positive revisions, closed
states, nonnegative bounded integer counters, scoped idempotency, one posting
per request/account/window, and one terminal settlement. Do not catch an
arbitrary `IntegrityError` as a duplicate: verify that a matching persisted
intent won before returning idempotently. Prove this lock order and crash
behavior with real PostgreSQL multi-process tests; SQLite and mocked locks are
not concurrency evidence.

## Request, lease and reconciliation semantics

Reservation creates the request, every account posting, the conservative
billable hold and strict decision audit atomically before any possibly billable
provider effect. A failure proven to occur before any provider bytes can
release money/concurrency holds, while retaining whatever abuse/rate count the
policy defines. A failure after possible I/O is not proof of non-execution.

Immediately before transport, acquire one random opaque dispatch token and
persist the single dispatch attempt with a short expiry. Expiry moves an
ambiguous attempt to `unknown`; it never makes the request claimable or eligible
for provider fallback. Continuation renewals advance the same fence only after
rechecking current grant epoch, sharing/binding revisions and authority. Lost
authority or a bounded control-service timeout blocks downstream work and may
attempt provider cancellation, but an unacknowledged cancellation retains the
maximum charge and concurrency hold through the defensible provider-completion
horizon.

Settlement is idempotent. Verified provider usage is applied once and releases
only the proven unused portion. Timeout, disconnect, crash, missing usage and
ambiguous dispatch retain the upper bound; reconciliation may conservatively
move that same amount from reserved to spent but never refund it on a timer.
Later authoritative evidence is an append-only adjustment, not a rewrite of
history. Reconciliation performs no provider invocation and no request replay.

Revocation increments/fences the grant epoch and immediately denies reserve,
dispatch and continuation. Transport status remains `revoking` while a dispatch
or continuation lease, unacknowledged cancellation or provider-horizon hold can
still represent live work; it becomes `revoked` only after those fences close.
Settlement of the original liability remains permitted after revocation and
charges its original account set. Never reactivate a revoked epoch or transfer
its liability to a replacement range, owner or pool.

## Idempotency and data-minimization boundary

Scope the caller idempotency key to the allocation/grant epoch, operation or
endpoint kind, and semantic request type. Store only domain-separated keyed
HMACs for the caller key and intent, plus key version and intent-contract
version. Never store the raw idempotency key, prompt, response, tool arguments,
tool results or an unkeyed body hash. Rotation must query every retained key
version so a retry cannot become a new provider invocation.

The versioned semantic fingerprint is produced at the future protocol-adapter
boundary and includes all billable or behavior-changing values: logical model
alias, protocol, bounded token/features, tool schemas and other normalized
request semantics. It excludes credentials and transport noise. Engine consumes
the fingerprint and bounded metadata; it does not need the body. A repeated key
with a different fingerprint conflicts. Pending or unknown duplicates conflict,
and completed requests may return safe status/accounting metadata but never a
retained response body. A request without a key is a new invocation.

The fingerprint key belongs in a runtime secret/keyring with rotation and
retention, not in the non-secret model catalog, ConfigMap, Terraform values,
process argv or participant environment. M04 defines the stored key-versioned
contract; M05 owns the authenticated transport and concrete secret mount. Do
not use `shared.cloud.sensitive_env` as permission to inject provider or HMAC
secrets into participant-controlled processes.

## Cross-cutting security and runtime passage

Paths below are relative to `shifter/shifter_platform` unless prefixed.

| Layer | Required passage |
| --- | --- |
| Authorization and policy gates: Engine allocation/grant services, sharing-authority fences, `shared.model_access.effective_policy` | Derive range, owner, generation and account references server-side. Recheck current grant epoch and complete authority at reserve/dispatch/continue; missing or stale evidence denies. Settlement uses the original immutable account vector and remains possible after revoke. |
| Shape and semantic validation: `shared.model_access`, installation `loader.py`/`model_access.py`, generated published schema, runtime catalog settings | Use closed DTOs, duplicate-key rejection, schema parity, canonical digests and bounded semantic validation. Publish account definitions as a new catalog contract version. Installer and runtime must reject unresolved refs identically; no free-form JSON side channel. |
| Provider boundary: `shared.model_access.provider` and the later broker adapter | Obtain a conservative `BillingBound` before reservation and normalize usage through `ProviderUsage`/`VerifiedUsage`. An adapter that cannot bound all enabled modalities/tools is unavailable. Provider exceptions and raw payloads never cross into public errors, audit or metrics. |
| Secret handling and OS exposure: installation runtime inventories, chart secret/config mounts, broker-only identity, GCP/AWS renderers, Terraform and process launch surfaces | M04 adds no provider credential delivery and no prompt/body persistence. Store only HMAC/key version references in the ledger. Future key material uses a broker/control secret mount, never argv, ConfigMap, rendered catalog, Terraform state, logs, images or guest environment. |
| Public error envelope: `shared.api.errors` and existing service/domain exceptions | Map authored domain outcomes to the existing 400/401/403/409/413/429/503/504 envelope at M05. Do not expose ceilings, balances, account topology, membership, prices, fingerprints, SQL state or raw validation/provider errors. |
| Audit, logs and metrics: `shared.audit`, `shared.log_sanitize`, `config.logging`, existing metrics publishers | Strict body-free decision/accounting audit commits before dispatch. Emit bounded stable reasons and safe correlations only. No prompt, response, fingerprint, key, credential reference, provider error, or per-user/range label. Control/database/audit failure fails admission closed. |
| Host/runtime and network: broker/control deployments, model-broker NetworkPolicy, range-cell firewall, runtime inventory allowlists | M04 remains an Engine service with no new public socket, network exception or guest process. M05/M08 must later authenticate the broker, preserve source/range binding and keep credentials outside the range. A ledger row is not transport authorization. |

There is no current cross-replica external audit-outbox/backlog authority. The
strict transactional audit is the M04 gate; a process-local health flag must not
be represented as a deployment-wide admission fence. M12 owns broader export,
backlog and provider-readback operation. Database or control-service loss fails
new admission closed within the documented timeout.

## Extensibility, verification and repository constraints

The required extension seam is a dimensioned, versioned account definition
with an explicit scope discriminator, plus a versioned semantic-request
canonicalizer. Provider variation stays behind the existing adapter ID,
`BillingComponent`, bound, usage and cancellation contracts. A new provider,
billing feature, tool protocol, account scope or UTC window must add validated
data/adapter support rather than branches in the ledger or a new ledger. New
dimensions reject until every accounting operation understands them.

Verification must cover concurrent last-unit reservations across distinct
processes, one shared account reached through overlapping selectors, distinct
caps on the same request, lower ceilings, account/pool revision changes,
membership removal and owner transfer, stale epochs, duplicate and changed
intent, HMAC rotation, integer overflow and rounding, every billing component,
crashes at reserve/dispatch/settle boundaries, stream disconnect, missing usage,
duplicate settlement, failed strict audit, lost control service, lease expiry,
late provider evidence and replacement generations. Use the existing PostgreSQL
lane and controllable provider-boundary contracts; label live-provider results
separately from local/synthetic proof.

Repository constraints in scope are `.importlinter`,
`scripts/check_layer_imports/layer_imports.yaml`, the ADR registry/exceptions,
`.pre-commit-config.yaml`, `.github/quality-path-filters.yaml`, the root
Makefile, the worker-reconciler chart, runtime inventory allowlists and generated
schema parity checks. Engine must not import CMS/CTF; owner layers reach Engine
through public services or the existing neutral authority port. Run ADR CI and
platform import checks, plus the native lanes for every installation, chart,
workflow or infrastructure surface actually changed.

## Non-goals and anti-patterns

M04 does not activate `ModelPendingGrant`, issue or hydrate credentials, add a
broker/API/authentication surface (M05), invoke provider SDKs (M07), enroll
ranges (M08), add UI (M09), implement full external telemetry/provider
reconciliation (M12), capture prompts under PLAT-215, promise exact provider
invoice caps, or add fair-share scheduling, distributed credits, Redis
authority, a new queue/daemon, a second range lifecycle, automatic provider
failover or operator fan-out scripts.

Avoid per-process counters; floating-point money; current-catalog settlement;
account IDs as policy; one table that conflates account definition, balance,
request and lease; summing overlapping postings as provider cost; timer refunds;
lease-expiry replay; response-body replay; generic audit actions; raw exception
logging; high-cardinality metrics; broker ORM access; provider-specific ledger
columns; secrets in argv/env/config; and tests that make pending grants usable
only to exercise accounting. None of the design prose or structural tests is a
claim that request accounting or provider access is deployed.
