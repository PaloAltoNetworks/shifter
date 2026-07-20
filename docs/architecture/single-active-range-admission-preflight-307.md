# Single Active Range Admission Preflight (#307)

Status: pre-implementation guidance

Date: 2026-07-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/307>

This note is intentionally not an implementation plan. Issue #307 is
requirement-free; its title, body, and expected behavior are the contract. The
invariant (resolved 2026-07-13, see below) is **at most one active range per
`(user_id, range_source)`** — a same-source admission guard that fixes the
reported duplicate-Mission-Control-range bug while preserving #450's deliberate
Mission Control + CTF coexistence.

## Contract Resolution And Scope Boundary

Issue #307's title ("one active range at a time") reads literally as a global
per-user invariant, which would supersede #450's per-source coexistence. That
fork was escalated to the issue owner during `/implement` and **resolved on
2026-07-13 to the per-source reading**: the enforced uniqueness key is
`(user_id, range_source)`, and #450's deliberate Mission Control + CTF
coexistence is preserved, not superseded. The issue body was amended to state
this scope. The reported production bug (an SE holding two simultaneous Mission
Control ranges) is a same-source race, which the per-source guard closes.

This change does **not** retire `RangeSource`, merge Mission Control and CTF
identity, or make CTF ranges visible through Mission Control projections. It is
not a scheduler rewrite, range lifecycle redesign, Engine/CMS model merger,
UI-only button disablement, or new quota/configuration system.

## Architecture Decisions And Guardrails

- CMS remains the range-admission authority. Reuse `cms.models.RangeInstance`
  and the public `cms.services` create facade for both cyberscript and
  ACES-native launches. Do not duplicate admission in Mission Control, CTF, the
  scenario hydrator, or Engine.
- Enforce the invariant in PostgreSQL as well as with the existing friendly
  service pre-check. A read-before-create check alone races. The database
  predicate must match the established CMS meaning of active: a non-soft-deleted
  row whose status is not `DESTROYING`. Terminal `DESTROYED` and `FAILED` rows
  remain historical through `deleted_at` and do not consume the slot.
- The uniqueness key is `(user_id, range_source)`, matching #450's per-source
  admission policy. Keep `range_source` as server-derived provenance for
  projections, history, audit, and the existing CTF boundary; it also partitions
  the active-range admission slot so Mission Control and CTF ranges coexist.
- Treat the CMS `Request` plus `RangeInstance` reservation as one database
  transaction. A constraint loser must not leave an orphan request and must not
  dispatch Engine/ACES work. Keep cloud dispatch outside the reservation
  transaction; preserve the existing transition to `FAILED` when an accepted
  reservation later fails to dispatch.
- Convert the expected uniqueness conflict at the CMS service boundary into the
  existing authored `CMSError` active-range message. Do not expose database
  exception text or a constraint name. Preserve the existing legacy flat error
  response and canonical shared API envelope unless API status semantics are
  deliberately changed under a separate contract.
- Apply the invariant to every ownership mutation, including
  `cms.services.reassign_range_owner` used by CTF spare recovery. Database
  enforcement is the backstop; service paths must translate a predictable
  collision without partially moving CMS or Engine ownership.
- Existing production duplicates are an operational prerequisite, not safe
  migration fodder. Identify and resolve them through the canonical lifecycle
  and cloud teardown paths before enabling the constraint. Do not pick a winner
  by timestamp, hard-delete rows, or mark database rows terminal without
  deprovisioning the corresponding infrastructure.
- Preserve request-id idempotency in `engine.services.create_range`; it solves
  duplicate delivery of one request, not concurrent admission of two different
  requests, and must not be confused with this invariant.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #307 |
| --- | --- | --- |
| Admission and persistence | `cms.services.create_range`, `create_aces_native_range`, `_assert_no_active_range`, `cms.models.Request`, `RangeInstance` | One CMS reservation path and one database invariant; both launch implementations must share it. |
| Active lifecycle meaning | `shared.enums.ResourceStatus`, `TERMINAL_STATUSES`, `RangeInstance.save`, `apply_terminal_soft_delete`, `SoftDeleteManager` | Reuse status and deletion semantics. Do not define another active flag or status set. |
| Provenance | `shared.enums.RangeSource`, `RangeInstance.range_source`, `ctf.bridges.cms_create_range` | Retain server-derived provenance; it is also the per-source uniqueness partition, preserving #450's MC + CTF coexistence. |
| Contracts and identity | `shared.schemas.RequestSpec`, `RangeSpec`, `RangeContext`, persisted-spec wrappers | Keep `RangeInstance.pk`, legacy `range_id`, Engine `Range.id`, and `Request.request_id` distinct; no duplicate DTO is needed. |
| Mission Control API | `LaunchRangeView`, `LaunchRangeSerializer`, `MissionControlAPIView`, `RangeLaunchRateThrottle` | Preserve authentication, actor binding, scopes, participant lifecycle policy, serializer validation, and fleet/actor backpressure. Rate limiting is not uniqueness. |
| CTF workflow | `ctf.services.range.provision_participant_range`, participant `select_for_update`, `ctf.bridges.cms_create_range`, `CTFRangeError` | Keep participant assignment serialization and the CMS bridge. Its row lock does not serialize a second product path for the same user. |
| Engine | `engine.services.create_range`, request-id idempotency, `Range.resolve_active_for_instance` | Do not add a competing admission policy or revert UUID-based terminal resolution. |
| Errors and logs | `CMSError`, `CTFRangeError`, `shared.api.errors`, `classify_user_message`, `safe_log_value` | Return authored messages, mask ownership, and log only sanitized identifiers and low-cardinality provenance/status. |
| Audit | `shared.audit.AuditEvent`, CMS provision audit, Mission Control request-context audit | Successful reservations retain the existing provision audit. Do not emit a successful provision event for a rejected duplicate. |
| Architecture enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard` | Mission Control and CTF continue through `cms.services`; no cross-domain model imports. |
| Production persistence tests | PostgreSQL CI lane in `.github/workflows/_quality.yml` | Prove the partial constraint and a real concurrent race on PostgreSQL; SQLite-only tests cannot establish production locking/constraint behavior. |

## Cross-Cutting Layers

- **Authentication and authorization:** Mission Control launch must continue
  through session/API-token authentication, `HasMissionControlActor`, the
  `mission_control:range:write` scope, participant lifecycle blocking, and DRF
  CSRF behavior for session auth. CTF launch must still pass organizer/event
  authorization and participant assignment locking before its CMS bridge. The
  duplicate check never reveals another user's rows.
- **Shape and policy validation:** `LaunchRangeSerializer`, CMS user/scenario/
  agent validators, the launchable-scenario registry, `RangeSpec`/`RequestSpec`
  validation, ACES package validation, and `RangeContext` projection validation
  remain in force. `range_source` stays an enum selected by server code, never a
  request-body or query-string field.
- **Persistence:** CMS owns the admission reservation (`Request` and
  `RangeInstance`); Engine owns realized runtime `Range` state; CTF owns
  participant assignment. The database constraint belongs with the CMS model
  and migration. Reassignment and terminal-state writes must preserve it.
- **Secrets and sensitive data:** This change needs no new credential, secret,
  header, cookie, token, SSH/RDP value, signed URL, or provider payload. Existing
  launch logs and errors must not gain any of those values; use the shared log
  sanitizer for request-derived strings.
- **Configuration and environment shapes:** No new Django setting, environment
  variable, feature flag, Terraform value, Kubernetes binding, cache policy, or
  secret binding is required. Existing database configuration validators and
  the PostgreSQL production/test backends see an ordinary schema migration.
- **OS/process exposure:** No new command, shell argument, process environment,
  scheduler payload, or provisioner argv is needed. The losing request must be
  rejected before any cloud task is dispatched, so it creates no extra runtime
  process or provider resource.
- **Error envelopes:** CMS raises the existing authored domain exception;
  Mission Control keeps legacy `{ "error": ... }` compatibility and canonical
  `shared.api.errors` envelopes; CTF retains `CTFRangeError`. Internal
  `IntegrityError`, SQL, stack traces, and constraint names never cross an HTTP
  or CTF service boundary.
- **Observability:** Preserve `user_id`, `request_id`, status, and server-derived
  `range_source` as sanitized correlation fields. Distinguish a duplicate
  admission rejection from dispatch failure. Do not log user email, request
  bodies, hydrated specs, provider responses, or secrets merely to diagnose the
  race.

## Extensibility Seam

The server-derived `range_source` field already partitions the admission slot
under #307's per-source key. That same boundary is the seam for a future,
explicitly contracted per-workflow quota: the policy can change at the single CMS
admission/constraint boundary without changing request bodies, scenario schemas,
CTF metadata, or Engine contracts. Do not add a runtime quota knob now; changing
a hard uniqueness policy must remain an intentional schema-and-service change.

## Gotchas And Anti-Patterns

- Do not treat the existing service pre-check, UI button state, DRF throttle,
  participant row lock, or Engine request-id idempotency as a concurrency-safe
  enforcement of the admission invariant.
- Do not use a global `user_id`-only uniqueness key: #307 was resolved to the
  per-source `(user_id, range_source)` key so #450's coexistence is preserved.
- Do not remove `range_source`, infer it from scenario/event/group data, or let a
  caller choose it.
- Do not use `RangeInstance.objects` versus `all_objects` inconsistently: normal
  admission excludes soft-deleted history; migration diagnostics intentionally
  need the full table.
- Do not make `DESTROYING` semantics diverge between the friendly query and the
  database predicate. Cancel and destroy currently reach that state through
  slightly different soft-delete behavior.
- Do not hold a database transaction open across Engine, ECS, ACES backend,
  broker, or cloud calls.
- Do not catch every `IntegrityError` as "active range"; translate only the
  named admission constraint and propagate unrelated persistence failures.
- Do not add a second exception hierarchy, status enum, range table, repository,
  DTO, lock service, queue, cache key, or workflow state machine.
- Do not silently repair existing duplicates with ORM-only status edits; that
  leaks infrastructure and falsifies audit/history state.

## Non-Goals

- No issue implementation, production cleanup, or formal Ground Control
  requirement/traceability work is performed by this preflight.
- No public API field, UI redesign, new RBAC permission, CTF schema, scenario DSL
  field, Engine/provisioner contract, launch-rate policy, or runtime config knob.
- No replacement of soft deletion, range event reconciliation, request-id
  correlation, CTF participant linkage, terminal instance resolution, or audit
  infrastructure.
- No change to how many instances, subnets, or applications one range may
  contain; the invariant counts range reservations, not range contents.

Architecture or `shifter/shifter_platform` changes on this path must pass the
repository's full ADR guard. Persistence/concurrency behavior must additionally
be exercised in the existing PostgreSQL CI lane, alongside focused CMS, CTF,
Mission Control API, ACES dispatch, Engine terminal-resolution, migration, and
import-boundary tests touched by the change.
