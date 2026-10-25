# CTF Communication API And Legacy Cutover Preflight

Date: 2026-09-19. Inspected baseline: `37f0b11be`. Scope: #2100 / CTF-012,
slice 3 of #2049. Architecture guidance only; no implementation plan or claim of
shipping behavior. Applies ADR-040, ADR-051-R2/R6/R9/R12 and ADR-052 alongside the
[delivery-engine preflight](ctf-communication-delivery-engine-preflight-2049.md).
Application paths below are relative to `shifter/shifter_platform/`.
`communication/` abbreviates `ctf/services/communication/` in the inventory.

## Existing Owners And Current Gaps

Expose the operations through `config/api_urls.py` → `ctf/api/urls.py` under
`/api/v1/ctf/`. The requirement's `ctf/urls.py` and `ctf/views/api/` references
describe legacy surfaces, not a second place to implement this API. Controllers
translate transport input to the existing `CampaignDraft` and communication
services; serializers project their results. Domain policy stays in
`ctf.communication_contracts` and `ctf.services.communication`, with Django ORM
transactions as persistence. No repository layer, messaging service or generic
workflow abstraction is missing.

The #2049 note's earlier baseline findings are not assertions about today's
code. Admission, due-time release, UTC/reference/audience bounds, scheduler claim
fences, backpressure and the in-app adapter now exist. The remaining exposure
risks are concrete:

| Current incumbent | Consequence for this slice |
| --- | --- |
| `communication/admission.py:reauthorize` rejects every token actor; `_actor_for_scheduled` reconstructs a token actor using only its row ID. | Registering scopes or checking them in a view is insufficient. Live token-owner authorization must work inside admission and at due time; retain and verify the original user/token association. |
| `communication/campaigns.py` authorizes before its write transaction; `revise_message` uses a caller's campaign state and has no actor parameter; `lifecycle.cancel_campaign` has no actor parameter. | Public authoring/revision/cancel must enter service-owned live authorization and serialization, not rely on an HTTP check around an otherwise unguarded mutation. |
| `actor_has_event_capability` already delegates to `resolve_event_authority`; it discards the returned authority source. | Reuse that resolver, including existing co-organizer support, and retain each target's authority for strict override audit. Do not add role comparisons or pretend platform-admin support is absent. |
| `ctf/api/serializers/communication.py` supplies read-only inbox and campaign summaries. | Extend these projections; they are neither write contracts nor authorization. No receipt interaction service currently exists. |
| `shared/api/strict_json.py:ClosedJSONParser` and `shared/api/closed_serializer.py:ClosedSerializer` already exist. | Reuse their closed parsing/shape boundary instead of copying the content-bundle parser. |
| `CTFCommunicationError` has a mapping promise in its docstring; the only general CTF response mapper found is private to `ctf/api/team_views.py`, forwards `str(exc)`, and defaults unknown subclasses to 409. | Consolidate the CTF boundary mapping in the existing API helper layer; do not copy the unsafe fallback or add a second exception hierarchy. `shared.api.errors` remains the envelope owner, with no shared-to-CTF import. |
| `_pagination_window` permits an omitted/invalid limit to mean unbounded; the summary serializer counts targets per object. | New collections need a finite default and maximum, deterministic ordering, scoped queries and bounded/preloaded aggregates. Reuse the conventions without inheriting unbounded reads or N+1 queries. |
| Only `InAppAdapter` is registered in `communication/adapters`. Legacy `_send_email` calls `send_email_async`; `_deliver_announcement` counts dispatch and publishes message bodies. | Email cutover cannot claim backend acceptance or keep this broad publisher. #1525 readiness is a dependency for enabling migrated email delivery, not permission to rebuild transport here. |

## Authority And State Boundaries

Organizer calls compose `config/_drf_settings.py`'s bearer-first/session chain,
`shared.api.principals.active_actor_user`, active account/profile checks, and
`shared.api_tokens.permissions.require_scope` with exact
`ctf:communication:read` / `ctf:communication:write` registered only in
`shared.api_tokens.scopes`. No wildcard, read-from-write implication, automatic
upgrade of existing tokens, or `ctf:event:*` / `ctf:play:*` substitution. Preserve
invalid-bearer fail-closed behavior even when a valid session cookie is present.
`request.user` is `None` for token authentication. Do not compose a new scope
permission with an undeclared `HasCTFEndpointScope` gate that rejects all tokens.

Public workspace input is a UUID resolved by `authorize_workspace`; an existing
campaign uses its persisted scalar binding through `authorize_bound_workspace`
with `USE_CTF_COMMUNICATIONS`. Its locked counterpart
`authorize_launch_workspace_locked` owns membership/archive serialization.
`resolve_event_authority(..., NOTIFICATIONS)` must admit **every** target, in
owner → delegated staff → platform-admin order, including collection/detail
reads. Access to one event does not disclose a multi-event campaign. A superuser's
event override does not bypass the separate workspace gate: that incumbent
requires membership and provides no implicit superuser exception. Do not synthesize
membership or import tenancy models to widen it.

Generalize token-owner eligibility within `shared.api_tokens`, reusing
`ApiToken.is_active` and `ApiTokenAuthentication`'s inactive/deleted/temporary-owner
denial. Admission consumes that owning boundary and exact scope, not a cached
HTTP result. Revalidate the persisted original owner/token pair on scheduled
execution and replay; deleting/revoking the token or actor must not turn work into
`AdmissionActor(system=True)`. `system`, origin, actor/token IDs, generation,
policy revision and early-release privilege are server-derived, never writable
serializer fields. Existing RAES/range trigger realization remains closed.
Opening ordinary token admission must not also open generic scheduler run-now:
preserve its session-only early-release boundary unless that operation explicitly
enforces communication authority/scopes on every target. Task lists must not leak
raw `task.error_message` or bypass campaign visibility.

Use the existing event-first deterministic locking and workspace/token owning
mutexes consistently with revocation, lifecycle and account offboarding. Check
the complete target set and locked current campaign/revision before mutation;
serialize revision numbering with release/cancel. `full_clean`, model docstrings
and `ImmutableFieldsMixin` do not enforce every relationship or bulk update.
Preserve campaign scope/targets, revision ownership, intent/snapshot pairing and
the release transaction's snapshots, commands, receipts and strict audit. Extend
`ctf.services.audit` / `shared.audit` for body-free authority/token/correlation
evidence; a single `_ctf_admin_authority` request slot is not evidence for multiple
targets. Audit failure rolls back database-only acceptance; no provider I/O runs
inside that transaction. Reuse occurrence idempotency and conflicting-replay
checks; HTTP retries must retain one bounded occurrence key rather than minting a
new one or re-resolving the audience.

Participant inbox/read/acknowledgement uses `IsAuthenticatedSession` plus live
participant policy, not `CTF_PARTICIPANT_PERMISSIONS` unchanged (it admits tokens).
Resolve the actor's authorized parent event as `_resolve_active_participant`
does, then match snapshot event, participant public ID and user together. No
ambient first participation, email lookup, caller-selected actor or receipt
creation for a nonrecipient/email-only intent. Keep the temporary-account marker,
`live_participant_for_user` and password-change gates; workspace membership is
not required of recipients. Archive must not erase otherwise authorized retained
inbox access, but does not extend temporary-account lifetimes. Keep viewing and
competition eligibility distinct, including disqualified participants' reads;
receipt mutations need their own explicit policy without granting play authority.
GET/list/preview and socket replay do not mutate receipts. Deliberate CSRF-protected
read/ack actions update server timestamps idempotently under live authority;
acknowledgement obeys the pinned policy, never derives from dispatch or a socket write.
Inbox visibility requires committed in-app availability, never a scheduled
declaration alone. Organizer summaries expose authorized bounded aggregates,
not recipient identities; accepted work, channel acceptance, socket delivery,
read and acknowledgement remain separate response meanings.

## Cross-Cutting Gates

| Layer | Required satisfaction and canonical owner |
| --- | --- |
| Bytes, JSON and shapes | Use `ClosedJSONParser` (duplicate members, nonfinite values, object root, depth and byte bounds) and `ClosedSerializer` at every writable nesting level. Parameterize the existing parser's byte ceiling for the whole envelope: its default 65,536 bytes cannot hold a maximum-size 65,536-byte body plus JSON escaping/other fields or the bounded reference lists. Body, envelope and list limits are distinct. Reject unsupported media types, unknown query/body fields and repeated singleton query keys. No free-form `JSONField` escape hatch or writable model serializer. |
| Domain validation and content | Delegate UTC, audience, trigger, channel, acknowledgement, link-host and digest semantics to `ctf.communication_contracts`; put missing bounds/type checks there for all callers. Current unhashable `kind`/channel/policy values can raise `TypeError`, escaped lone surrogates can fail UTF-8 encoding, and unexpected-key errors echo attacker-controlled names. These must be bounded authored rejections. Regex Markdown checks and the general `MarkdownContent.tsx` renderer do not prove ADR-051's no-media/allowlisted-link profile: extend that canonical renderer through the ADR's closed profile parameter and adversarial fixtures, with render-time enforcement, no URL fetching, raw HTML or CSP relaxation. |
| Errors and telemetry | One CTF-code-to-status/authored-message mapping feeds `shared.api.errors`; validation, opaque unavailable-object denial, conflict, throttling and dependency unavailability remain distinct. Reuse the 429/`Retry-After` versus 503 posture in `mission_control.api.rate_limit`; inspect actual communication pressure/cache exceptions. Never forward `str(exc)`, model/parser/provider text or arbitrary `details`. `safe_user_message` is not redaction; `_normalize_detail` retains arbitrary string values and dictionary keys. Use `RequestIDMiddleware`, `shared.log_sanitize`, `ctf.services.communication.metrics` and `config.logging.ECSFormatter`'s allowed fields, with bounded correlation and no bodies, coordinates, credentials or high-cardinality metric labels. Inspect traceback/exception-chain logging too. |
| Admission and persistence | Keep `communication.backpressure`'s shared rate limits and PostgreSQL outstanding-work serialization; release limits alone do not bound draft creation, revisions or inbox query cost. Bound those operations using existing rate/storage/query patterns, including target lists before database lookups and audience resolution before full materialization. ORM writes and migration conversions preserve uniqueness, retained replay evidence, encrypted coordinates, physical retention erasure and `PROTECT` relationships during account/event deletion. No process-local limiter, Redis workflow truth or second outbox. |
| HTTP/WebSocket/browser | Preserve `CTFAccountBoundaryMiddleware`, session CSRF and endpoint authority: the `/api/v1/ctf/` path admits temporary accounts to routing, not organizer operations. WebSocket admission remains `AllowedHostsOriginValidator` → `AuthMiddlewareStack` → `CTFAccountWebSocketBoundary` → `SharedNotificationConsumer`. Add only exact `/ws/notifications/` after live-participation/password-change checks; retain topic authorization and recheck on fetch/read/ack. Reuse `publish_communication_wakeup` with explicit recipient and snapshot ID; browser polling/reconnect recovers the durable inbox. Audit old replay rows/payload handlers so opening the socket cannot revive retained broad-content legacy payloads. |
| Secrets and OS exposure | Coordinates stay in `EncryptedStringField`; only the dependent channel may decrypt them. Credential issuance stays in `ctf.services.participant.credentials` with `shared.credential_delivery` rate/audit concerns and tokenless login URLs. No password, token or volatile `ParticipantPasswordIssuance` in retained revisions, scheduler metadata, migration diagnostics, API examples, argv or shell interpolation; retry never rotates a credential. Existing `entrypoint.sh`/`entrypoint-lib.sh` hydrate secret references privately. This slice needs no new worker secret or job credential. |
| Settings and deployment shapes | Reuse `config/_ctf_communication_settings.py`, `_email`, `_channels`, `_cache_settings` and `_redis`; preserve fail-loud startup and Redis TLS/AUTH/shared-cache posture. Any new exposed limit/cutover control must pass `_env_manifest.py` plus generated `env-manifest.json`, `shifter/installation/runtime_inventory*.py`, runtime render/bootstrap scripts, closed Helm values schema and templates, GCP base/overlays, Compose and AWS EC2/deploy process lists inventoried in the #2049 note. No arbitrary env knob or second WebSocket enablement flag. If an implementation introduces job env transport, `shared.cloud.sensitive_env.split_env` and Kubernetes admission are separate gates; `EMAIL_API_KEY` currently matches neither sensitive-name nor suffix rules. Never serialize it as literal job env. |
| Public contract and workflow | `PlatformAutoSchema` consumes `require_scope` for `x-required-scopes`; explicitly document participant operations as session-only without advertising bearer access. Generate `openapi/v1.json` with `manage.py api_contract` and `frontend/src/api/schema.d.ts` with the existing `gen:api` script. Use drift, generated-types and trusted-base breaking-change gates in `.github/workflows/_quality.yml`; encode closed alternatives and bounds in that generated contract, with no hand-maintained parallel schema/client. Keep ADR-040 compatibility/retirement rules, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `.pre-commit-config.yaml`, quality path filters and `.ground-control.yaml` workflow conventions. Documentation/traceability must describe the completed slice, not declare the umbrella requirement delivered. |

## Controlled Cutover

The cutover boundary covers all producers, not only the new routes:
`ctf/api/organizer/notifications.py`, legacy `ctf/views/api/notifications.py` and
`views/admin_notifications.py`, `ctf.services.notification`'s exported functions,
event/range lifecycle callers, `CTFScheduledTask` and its `SEND_NOTIFICATION`
handler. Only one writer may own a migrated occurrence. A database conversion
does not stop old pods, claimed tasks or process-local email threads: activation
requires fenced/quiesced old producers and reconciliation of `RUNNING`/`SENDING`
work before the new writer is admitted. Rolling deployment and rollback must
preserve that single-writer condition; rollback cannot simply restart legacy
sending against already migrated work.

Use bounded, restart-safe conversion with stable legacy-row/occurrence mapping
and atomic row/task ownership transfer. Validate scope, actor, content, due time
and selected channels through the same domain contract. Invalid/orphaned or
ambiguous rows block cutover with bounded diagnostics; no privileged system
fallback, silent truncation, dropped task or blind resend. Historical sent counts
remain explicitly legacy aggregate evidence; neither successful recipients nor
inbox read/ack history may be invented. In-flight external outcomes can remain
unknown; database rollback cannot recall an email.

Email remains #1525. If its adapter is unavailable, do not enable the migrated
email delivery claim, silently select in-app instead, or leave commands presented
as deliverable forever. Record the channel-readiness dependency in activation
evidence. A valid staged conversion is not completed email cutover. Non-secret
login/access notices can use the ledger; secret issuance remains volatile at its
existing owner and is never replayed from a message revision.

Compatibility routes may project the new services during a bounded transition,
but cannot keep a bypass under broad event scopes, independently send, or return
`sent` for mere acceptance. Scope tightening and response semantics affect real
clients even if the OpenAPI diff misses them. Publish the migration contract;
ordinary breaking changes follow ADR-040's parallel-major policy, and actual
retirement needs accepted `openapi/v1.retirements.json` metadata. Do not weaken
the contract checker to make cutover pass.

## Extensibility And Required Evidence

The extension seams remain the existing `CampaignDraft`/immutable revision,
validated `AdmissionActor` and source normalizer, closed audience/trigger/channel
enums, and `DeliveryCommand`/`DeliveryOutcome`. Future channels extend the adapter
contract; future content adds a pinned profile; operational budgets and the HTTP
envelope ceiling are bounded server-owned parameters. None requires new routes
per transport, arbitrary metadata, a runtime plugin registry or provider-aware
controllers. Keep credential material outside these seams.

Extend existing `tests/ctf/test_communication_*`, token/authority/workspace/API
contract tests, `test_bootstrap_credential_hardening.py`, shared consumer tests
and `tests/integration/asgi/test_notifications_*`. Evidence must include negative
scope/session/CSRF and multi-event isolation, revoked/deleted token-owner pairs at
due time, privileged override audit rollback, malformed nested types/duplicate
keys/size boundaries with envelope and log leak assertions, idempotent receipt
actions, and legacy producer/migration/restart/rollback interleavings. Use the
root `Makefile` PostgreSQL and Redis lanes for real concurrency and ASGI evidence;
SQLite or mocked first-party services cannot prove those boundaries. Exercise
release/revision/cancel and revocation races, audit failure, soft deletion/purge,
unavailable channels and historical aggregate preservation. Run the repository's
ADR guard and stack/import checks plus the affected API/frontend/schema gates;
runtime/manifests checks apply if those surfaces change. A green ADR registry is
structural evidence only.

Non-goals: implementing this preflight; redesigning slices 1–2; implementing
#1525 email transport, new RAES/range ingress, chat/webhook adapters, new UI or rich
content features; another scheduler, outbox, exception hierarchy or authorization
system; exactly-once external delivery or recall. Existing owners must be hardened
where API exposure reveals a gap; their policy must not be duplicated in views.
