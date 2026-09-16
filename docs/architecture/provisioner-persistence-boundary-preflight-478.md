# Provisioner Persistence Boundary Preflight (#478)

Status: pre-implementation guidance

Date: 2026-07-21

Issue: GitHub #478, "Provisioner is coupled directly to Django schema via raw
SQL and migration-time grants"

This is a requirement-free architecture run. The issue is the shipping
contract. This note fixes the service and data ownership boundary; it is not an
implementation plan.

## Decision Boundary

Engine owns the request, range, instance, app, subnet, allocation, launch,
outbox, and audit persistence schemas. The separately deployed provisioner
must not treat those schemas as its API.

Keep PostgreSQL as the durable handoff already shared by both runtimes, but
replace table-shaped integration with operation-shaped contracts:

1. `ProvisionerLaunchIntent` remains the canonical command outbox and source
   of the stable `operation_id`, command validation, generation fencing,
   idempotency, retry, and task identity. Its command payload stays minimal and
   secret-free. This operation/launch handoff must become provider-neutral;
   AWS cannot keep bypassing the generation merely because its TaskRunner is
   currently invoked synchronously.
2. Engine materializes one immutable, versioned, secret-free operation input
   projection keyed by that `operation_id`. The projection is separate from
   launch scheduling state and is built from Engine-owned models through the
   existing shared contract validators. It is not a copy of Django tables.
3. The provisioner consumes only that input projection and appends versioned
   results to a dedicated Engine-owned result inbox. It never updates domain
   tables or inserts range-event outbox rows.
4. An Engine-owned result applier validates, fences, and idempotently applies
   inbox results through Engine services. Domain state, audit intent, and any
   `RangeEventOutbox` notification commit in the same platform transaction.
5. Standard range events remain notification-shaped propagation signals under
   ADR-025. The result inbox is not an event topic, a public API, or another
   source of domain truth.

The delivery model is at-least-once with idempotent application, not
exactly-once. A unique result identity plus the operation generation and a
payload digest must distinguish a harmless replay from the same identity
arriving with different content. Unknown contract versions, stale generations,
wrong resource ownership, invalid state transitions, and conflicting replays
fail closed without mutating domain state.

```text
CMS/Engine authorization
        |
        v
Engine transaction --> launch intent + immutable operation input
                                      |
                                      v
                                provisioner task
                                      |
                                      v
                              append-only result inbox
                                      |
                                      v
Engine result applier --> domain state + audit + range-event outbox
```

## Contract Ownership And Shape

The transport envelope needs only a closed discriminator and correlation:
`contract_version`, `operation_id`, `request_id`, `resource`, `operation`, and
one bounded resource-specific payload. Contract version is independent of
application/image release versions. Producer and consumer must publish a
rolling compatibility policy; removing an accepted version requires evidence
that no retained input or replayable result still uses it.

Payloads must compose existing contracts rather than re-model them:

- Cyberscript ranges use the existing persisted `RangeSpec` envelope and
  `shared.schemas` validation; ACES ranges use the serialized compiled
  `ProvisioningPlan` and the ADR-032 consumer validation.
- GCP range-cell inputs/results reuse `shared.range_cells`; backend and purpose
  reuse `shared.range_instantiation_policy`.
- Remote access reuses `shared.remote_access`; payloads carry capabilities or
  provider secret references, never VPN profiles or credential values.
- ACES content uses `shared.aces.content_delivery` and the existing immutable
  delivery binding; image candidates are a bounded projection of the canonical
  Engine image registry, not a registry dump or second image schema.
- Lifecycle vocabulary reuses `shared.enums.ResourceStatus` and the existing
  Engine transition authorization in `engine.launch_intents` and services.
- Legacy range/NGFW output normalization reuses `state_helpers` and the
  existing NGFW attachment/config parsers. If a legacy output shape lacks a
  shared runtime parser, formalize that shape once in a dependency-light
  `shared` contract consumed by both runtimes; do not add matching ad hoc
  validators on each side.

Input and result payloads are operational contracts, not ORM DTOs. They must
not expose model primary-key joins, column names, table names, arbitrary
`**kwargs` updates, Django migration history, or a generic repository/query
language. Adding a new resource or operation extends the discriminator and one
contract adapter; it does not add another table grant or transport.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| User/domain authorization | CMS create/destroy/NGFW services; Engine lifecycle services | A provisioner result is not proof of end-user authority. Resolve the persisted operation and re-check current ownership/state. |
| Command validation and fencing | `engine.launch_intents`, `Range.provisioner_operation_id`, `Instance.provisioner_operation_id`, `ProvisionerLaunchIntent` | Extend this operation identity; do not invent a second request generation or idempotency vocabulary. |
| Task dispatch | `engine.ecs`, `shared.cloud.types.TaskRunner`, AWS/GCP task runners, GCP admission policy | Keep argv to the canonical operation plus UUID correlation. Do not send JSON or secrets in argv. |
| Domain persistence | `engine.models`, `engine.services`, `transaction.atomic`, `select_for_update`, model constraints | Only Engine applies results. Keep one writer and one state-transition implementation. |
| CIDR reservations | `SubnetAllocation`, provisioner network inventory adapter, PostgreSQL lock/uniqueness semantics | Reservation is synchronous coordination needed before cloud mutation, not an eventual result. Put it behind an Engine-owned stable command/service boundary without weakening its serialization or drift checks. |
| State shaping | provisioner `state_helpers`, NGFW config/attachment parsers, `shared.range_cells`, `shared.remote_access` | Reuse normalized, reference-only state; do not persist raw provider responses or parallel state documents. |
| Durable notification | ADR-025, `RangeEventOutbox`, its drainer/DLQ, `reconcile_range_events` | The result applier creates notifications atomically with Engine state. Do not let the provisioner write the event outbox or put full state in events. |
| ACES evidence/status | `shared.aces.operations`, Engine ACES status/evidence services, ACES sidecar schemas | Preserve record idempotency, timestamp ordering, bounded diagnostics, and the standard range-status projection path. |
| Audit | `shared.audit`, Engine handler/service audit calls | Audit the applied domain transition, not transport receipt; never copy raw inbox payloads or provider errors into audit context. |
| Errors | `shared.errors`, `shared.api.errors`, `shared.cloud.exceptions`, existing Engine service errors | Add at most one boundary parse error, not a hierarchy. Persist fixed reason codes and bounded authored messages. |
| Logging | platform `shared.log_sanitize`, provisioner `log_redact`, both ECS formatters | Log operation/result ids, contract version, result kind, attempt, and safe status. Never log payloads, DB tokens, secret refs requiring masking, or raw provider exceptions. |
| Tests | PostgreSQL semantics lane, launch/outbox/reconciler tests, provisioner wire and boundary-contract tests, ADR-019 | Prove real constraints, locks, grants, replay, and service behavior. Mock only DB/cloud/process boundaries, not first-party services. |

## Cross-Cutting Security Layers

The intended design must pass every layer below.

1. **External auth and domain policy.** Existing DRF/session/token permissions,
   CMS ownership/launchability checks, CTF policy, and Engine lifecycle
   validation remain the only user authorization path. No unauthenticated
   callback endpoint is introduced. The result applier resolves the server-
   created operation, locks its current Range or NGFW Instance, checks
   operation generation and allowed lifecycle state, and rejects payload-owned
   user/range associations.
2. **Wire validation.** Engine validates before persisting an input; the
   provisioner validates again before cloud mutation; Engine validates each
   result before applying it. Validation is closed on keys, types, enum values,
   UUIDs, counts, depth, text length, and serialized byte size. A `TypedDict`,
   JSONField, digest, or database constraint is not a runtime parser.
3. **Database authentication and grants.** Keep the existing TLS/IAM-token
   connection path in `provisioner_db.get_db_connection`, `cloud.{aws,gcp}.db_auth`,
   RDS IAM, and Cloud SQL workload identity. At cutover the provisioner role may
   retain only database connect/schema usage, read access to the immutable
   integration input, append access to the inbox, and any explicitly reviewed
   execution right for synchronous reservation coordination. Revoke SELECT,
   UPDATE, DELETE, sequence, and outbox grants on Django domain tables with a
   forward migration; never edit historical migrations or broaden grants to
   make rollout easier.
4. **Secret handling.** Operation inputs/results may contain existing encrypted
   persisted envelopes and provider-native secret references, but never
   plaintext credentials, private keys, database tokens/passwords, signed
   URLs, VPN profiles, guest command input, sensitive environment maps, or raw
   Secret objects. Continue through `shared.cloud.sensitive_env`, provider
   secret stores, `FIELD_ENCRYPTION_KEY` handling, and the reference-only state
   parsers. Result/inbox retention must assume database readers can see every
   retained row for this workload-level principal.
5. **Environment and deployment shape.** Reuse provisioner `config` parsers,
   installation runtime inventory, platform env manifest, GCP runtime renderer,
   AWS task definition, Helm/base manifests, and GCP admission env allowlists.
   A table contract needs no new endpoint/token env. After event-outbox writes
   leave the provisioner, remove its event-topic binding rather than leaving a
   misleading capability. Any env change must be reflected in every renderer
   and validator, not read with a new module-local `os.environ` spelling.
6. **OS/process exposure.** Process argv contains only the allowed resource,
   operation, request id, and operation id. Payloads and capabilities are read
   through the integration store, not shell strings, command-line JSON,
   Terraform CLI variables, Kubernetes literal env, logs, or temporary files.
   Database and field-encryption credentials remain secret-backed environment
   inputs where already required and must never be printed or passed to child
   processes.
7. **Error envelopes.** Parser/provider/DB exceptions map once to stable
   internal reason codes and the existing bounded lifecycle failure messages.
   DRF responses continue through `shared.api.errors`; websocket/events remain
   notification-shaped. Raw SQL, table names, provider bodies, tracebacks,
   secret identifiers, and result payload fragments must not reach Range error
   text, audit context, browser JSON, or websocket messages.
8. **Observability and recovery.** Reuse management-command worker heartbeats,
   structured ECS logs, launch/outbox retry conventions, and AWS/GCP alert
   parity. Operators need signals for oldest unapplied result, result retry/DLQ,
   unsupported version, stale/conflicting replay, operation with no terminal
   result, and any remaining compatibility-path SQL/grant use. A task can crash
   after cloud mutation and before result append, so immutable input and
   provider/Terraform state must permit an idempotent re-drive or reconcile;
   ADR-025's CMS reconciler alone cannot recover a missing provisioner result.

The shared DB principal is still a workload-wide trust boundary, not per-range
authorization. Generation and ownership checks contain stale or accidental
cross-operation writes; they do not turn a compromised provisioner identity
into a tenant-isolated principal. Do not claim otherwise or expand cloud IAM as
part of this issue.

## Persistence And Migration Guardrails

The current coupling spans more than the issue's original examples. Active
provisioner SQL reaches `mission_control_range`, `engine_request`,
`engine_instance`, `engine_app`, `engine_subnet`,
`engine_subnetallocation`, `engine_aces_content_delivery_binding`,
`engine_aces_image_mapping`, and `engine_range_event_outbox` from
`provisioner_db*`, `ngfw_runtime`, `range_ops`, `config/_range.py`,
`range_backend_evidence.py`, and `components/network`. Historical Mission
Control and Engine migrations grant still more columns/tables. Completion must
reconcile the actual SQL inventory with the effective PostgreSQL privileges;
deleting one helper or revoking only the grants named in the migrated issue is
insufficient.

Compatibility may be incremental, but each operation generation has exactly
one authoritative result path. Shadow-read and compare is acceptable; applying
both direct writes and inbox results is not. Compatibility adapters stay behind
the existing provisioner DB/state call seams so orchestration code does not
branch on old/new transport. Every migrated operation family must cover
provision, destroy, pause/resume, failure/compensation, NGFW, ACES, content
delivery/image lookup, backend evidence, and subnet reservation before its old
grant is revoked. A final PostgreSQL effective-privilege test must prove the
domain-table and range-event-outbox grants are gone.

`range_config` is authored/compiled intent, not a scratch state document.
Today subnet allocation mutates it with realized CIDRs and later repairs it
from `SubnetAllocation`; the new boundary must not preserve that concept
confusion. Reservations and realized subnet state belong in their existing
Engine allocation/subnet ownership surfaces and in the immutable operation
input/result, while persisted authored intent remains unchanged.

## Extensibility Seam

The seam is one versioned **provisioner operation contract**, parameterized by
`resource`, `operation`, and payload contract version, and anchored to the
existing `operation_id`. Result kinds may represent progress, resource state,
terminal success, or terminal failure, but their legal ordering and finality
are closed per operation family. The next provider, resource type, or lifecycle
operation should add a contract adapter and Engine applier without changing the
integration grants, creating another inbox, adding table-shaped fields, or
editing every caller.

Keep launch retry, result-apply retry, notification delivery, and projection
reconciliation as separate policies. They can share locking/backoff helpers,
but not tables, status enums, payloads, or DLQ meaning.

## Whole-Repo Boundary

Implementation must account for these repository surfaces even when a given
file needs no edit:

- Engine command/persistence: `engine/launch_intents.py`, `engine/ecs/`,
  `engine/models/`, `engine/services/`, Engine management-command workers and
  migrations;
- provisioner adapters and call sites: `provisioner_db*.py`, `ngfw_runtime.py`,
  `range_ops/`, `range_subnet_allocation.py`, `range_backend_evidence.py`,
  `config/_range.py`, `components/network/`, `state_helpers.py`, and
  `events.py`;
- shared contracts: `shared.schemas`, `shared.messages`, `shared.enums`,
  `shared.range_cells`, `shared.range_instantiation_policy`,
  `shared.remote_access`, `shared.aces`, `shared.audit`, `shared.errors`, and
  `shared.log_sanitize`;
- recovery/projections: `RangeEventOutbox`, `drain_range_event_outbox`, Engine
  handlers, CMS range handlers, `reconcile_range_events`, Mission Control
  fanout, and CTF bridges;
- runtime/security: AWS engine-provisioner task definition/IAM/RDS grants, GCP
  Cloud SQL IAM, `shared.cloud.sensitive_env`, GCP task runner, base and Helm
  provisioner Job admission, service accounts/RBAC/network policy, runtime env
  renderers, installation inventory, and `config/env-manifest.json`;
- enforcement/evidence: `.importlinter`, ADR-019 boundary-mock policy, the
  PostgreSQL semantics lane, provisioner mypy/pytest/wire tests, platform
  service/outbox/reconciler tests, migration proof, ADR guard, and both provider
  deployment render tests.

## Gotchas And Anti-Patterns

- Do not use `RangeEventOutbox`, SNS/SQS, Pub/Sub, Redis, or websocket payloads
  as the result inbox; those contracts are notification-shaped and fan out.
- Do not put full provider state into range events or make consumers query a
  new result blob instead of Engine models.
- Do not persist table/column-shaped DTOs, raw provider responses, generic
  patches, arbitrary SQL, or caller-selected model field names.
- Do not add a second status enum, event constant set, ACES/range schema,
  remote-access schema, validator, exception hierarchy, logging sanitizer, or
  retry framework.
- Do not treat a shared module's type annotation as sufficient validation at
  either process boundary.
- Do not perform an unprotected DB-plus-broker dual write or acknowledge/delete
  an inbox row before domain state and notification intent commit.
- Do not allow a stale terminal result to overwrite a newer lifecycle episode,
  and do not silently accept the same result id with a different digest.
- Do not leave subnet allocation as an undocumented direct-table exception or
  weaken its PostgreSQL serialization. It is the main synchronous-coordination
  gotcha in this migration.
- Do not retain provisioner mutation of `range_config`; it conflates authored
  intent with allocation/runtime state.
- Do not add an internal HTTP callback merely to avoid SQL unless its
  cross-cloud workload authentication, authorization, replay, availability,
  and error-envelope costs are explicitly accepted in a later ADR.
- Do not edit historical grant migrations, retain unused grants “just in
  case,” or declare completion while the runtime principal can still mutate
  Django-owned tables.
- Do not remove the DB path before crash-after-cloud-mutation recovery,
  rolling-version compatibility, retention, worker liveness, and DLQ ownership
  are demonstrably in place.

## Non-Goals And Implementation Boundary

- No cloud resource orchestration, Terraform/Pulumi state, TaskRunner, provider
  adapter, scenario DSL, or ACES model redesign.
- No public API, user authentication, CTF authorization, Mission Control,
  websocket, Guacamole, terminal, or participant-access behavior change.
- No event sourcing, broker replacement, generic workflow engine, repository
  layer, controller family, or cross-service ORM package.
- No broad request/range UUID refactor from #302 and no separate duplicated-
  constant cleanup from #273 beyond consuming their canonical shared values.
- No claim of per-tenant isolation for the provisioner workload identity and no
  cloud-IAM expansion to compensate for the persistence migration.
- Legacy grants and direct SQL are temporary rollout shims only. New feature
  work must not add another direct-table dependency while this migration is in
  progress.
