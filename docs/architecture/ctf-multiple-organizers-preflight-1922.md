# CTF multiple-organizer preflight (#1922)

Status: pre-implementation guidance

Date: 2026-08-14

Requirements: none; GitHub issue #1922 is the authoritative contract

This note fixes the repository-wide authorization boundary for one canonical
CTF event owner plus multiple full co-organizers. It adds no runtime role,
route, serializer, migration, task, or UI behavior and is not an implementation
plan.

## Decision and concept boundary

Extend the existing `CTFEventStaff` and event-capability policy. Do not add an
event-organizer many-to-many field, a second membership table, a Django group
per event, a workspace role, or another authorization service.

- `CTFEvent.created_by` remains the one non-null, `PROTECT`ed canonical owner.
  It is lifecycle/ownership identity, not the complete set of event
  administrators.
- `CTFEventStaff` remains the one event-scoped assignment model. Add a full
  organizer role beside moderator and judge; an owner never also has a staff
  row.
- A platform `CTF Organizer` role admits organizer surfaces but grants no event
  by itself. Event authority is the union of exact ownership and one live
  `CTFEventStaff` assignment evaluated by the CTF service policy.
- Moderator keeps exactly `participants` and `notifications`; judge keeps
  exactly `awards` and `submissions`. Adding the organizer role must not widen
  either map or let one bounded capability imply another.
- A co-organizer receives every operational event capability, including event
  configuration, challenges/flags/hints/files/prerequisites, participants,
  teams, ranges, scoring/scoreboard, notifications/templates/webhooks,
  analytics/exports, event content/pages, lifecycle, and deletion. Existing
  state, confirmation, secret, range, and destructive-action safeguards remain
  additive.
- Authority-topology changes stay owner-only: list/assign/re-role/revoke event
  staff and transfer canonical ownership. The staff-revocation command must
  never target `created_by`; there is therefore always exactly one owner, not a
  count of interchangeable owner rows.

The current capability selector uses `None` to mean owner-only. Retire that
implicit convention. Define a closed event-operation/capability vocabulary and
one role-to-capability map at the existing `ctf.services.event.staff` policy
seam. Every event resolver and service assertion must receive an explicit
operation; owner-only operations use an explicit owner predicate/operation.
Unknown roles and operations deny. Do not use an `all`, `admin`, or wildcard
grant that silently authorizes a future operation.

Older issue-specific preflight notes describe their then-current policy as
exact `created_by` ownership. For operational surfaces in #1922, the canonical
interpretation becomes the matching event capability. Exact ownership remains
authoritative only for the owner-only operations above and canonical
attribution.

No new ADR is required while the change remains inside the CTF-owned event
model and preserves ADR-001 layer ownership, ADR-040's runtime-first v1
contract, ADR-046's separation from workspace tenancy, and the existing
provider/range boundaries. A generic platform RBAC model, multiple canonical
owners, workspace-derived event authority, or changed CMS/Engine ownership
would require a separate accepted decision.

## Persistence, transfer, and mutation invariants

Keep the current conditional uniqueness of one live staff row per
`(event, user)` and soft-deletion semantics. Add a database check constraint
derived from the closed `EventStaffRole` values; model `choices`, serializer
validation, and `CTFBaseModel.full_clean()` are useful layers but are not the
final authorization-data boundary.

Staff assignment, re-role, revocation, and ownership transfer are atomic
authority mutations. Lock the `CTFEvent` as the stable per-event mutex, then
re-read the actor and affected live assignment under that lock. This prevents a
transfer and revocation, or two role changes, from authorizing against different
owners. Translate conditional-unique/check conflicts into existing bounded CTF
errors; never expose `IntegrityError` or database text.

Only the locked current owner may mutate assignments. The target must be an
active, non-temporary platform user who already has the canonical CTF Organizer
role; an event assignment must never create or repair that global role. The
closed request role is validated with a DRF `ChoiceField` and again in the
service. The target may not be the canonical owner. These rules prevent a
co-organizer, moderator, judge, standard user, or token scope from escalating
itself or another account.

Ownership transfer is one locked service command, not a client sequence. The
target must already be a live co-organizer. In the same transaction, make the
target `created_by`, remove its now-redundant staff row, and retain the previous
owner as a co-organizer. The non-null owner invariant is never transiently
broken. Event ownership transfer does not transfer participant accounts,
teams, CMS/Engine ranges, workspaces, API tokens, cloud resources, or provider
credentials; those objects retain their existing product-specific owners.

A removed co-organizer disappears from organizer listings and fails the next
HTML, REST, service, and WebSocket authorization check. Its session or API
token may remain valid globally, but event scope plus token scope is still
required, so the credential no longer grants this event. A background command
already durably accepted while the actor was authorized remains a system-owned
task; removal does not turn workers into credential replayers or silently undo
accepted work.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Owner and assignments | `ctf.models.CTFEvent.created_by`, `CTFEventStaff`; `EventStaffRole` | One owner FK plus one conditional-unique live assignment. No parallel schema, JSON role list, signal-owned authority, or per-event Django group. |
| Event policy | `ctf.services.event.staff.actor_has_event_capability`; `ctf.services.authorization`; organizer `_base` resolvers | Evolve one fail-closed operation map and one raising service assertion. Do not leave direct `created_by_id` checks or duplicate role queries on operational paths. |
| Platform admission | `shared.auth`, `ctf.bridges.get_user_role`, `ctf_organizer_required`, `CTF_ORGANIZER_PERMISSIONS` | Global organizer status is admission, not event authority. Staff/superuser, workspace roles, CTF teams, provider claims, and navigation state are not substitutes. |
| API principal and scopes | `ApiTokenAuthentication`, `SessionAuthentication`, `active_actor_user`, `HasCTFEndpointScope`, `ctf:event:{read,write}` | Bearer auth stays first/fail-closed; session CSRF and exact scopes remain. A token acts only as its active owning user and never embeds an event role. |
| HTTP shapes and errors | Explicit CTF DRF serializers; `_CtfApiError`; `CTFError` subclasses; `shared.api.errors` | Use `CTFPermissionError` for service denial, validation/state errors for their existing meanings, and the request-ID v1 envelope. No new exception tree, raw `JsonResponse` on new v1 behavior, or leaked ORM/error details. |
| Event validation | `EventWriteSerializer`, `_EVENT_MUTABLE_FIELDS`, `_validate_*` event services, model validators/full-clean; challenge/participant/range services | Authorization only admits the caller. It never bypasses mass-assignment filtering, state transitions, content hydration, scoring, range admission, SSRF/file, or model validation. |
| Secrets and content | `EncryptedStringField`, native flag services/models, CTF S3 helpers, CMS/Engine secret and range facades | Co-organizers use the same services. Never project or audit participant passwords, flag material, presigned URLs, provider secrets, raw content, or credentials. |
| Listing/read projections | `get_organizer_events`; `EventSummarySerializer`, `EventDetailSerializer` | Make the existing query owner-or-live-co-organizer and de-duplicate it. Retire the unused duplicate `list_events_for_organizer` rather than maintaining two policies. Publish server-derived access role/capability hints for presentation. |
| SPA | `frontend/src/api/{client,ctf,ctfAdmin,ctfAdminOps}.ts`, `ctfKeys`, generated `schema.d.ts`, CTF admin pages/cards | Reuse one same-origin client, CSRF/error/request-ID behavior, generated types, and TanStack invalidation. Capability hints hide/disable owner-only controls but never authorize them. |
| Realtime | `shared.notifications`, `SharedNotificationConsumer`, `ctf.services.notification.realtime` | Preserve topic parsing/registration, authenticated subscription, per-recipient rows, bounded replay, and best-effort fanout. Event policy and live organizer-recipient derivation remain CTF-owned. |
| Background work | `CTFScheduledTask`, event scheduling services, `run_ctf_scheduler`, CMS/Engine bridges | Authorize and audit the interactive command before enqueue/control. Workers resolve durable event/task state as system actors; never serialize cookies, bearer tokens, emails, or a synthetic human role into task payloads. |
| Audit and logs | `shared.audit`, `ctf.services.audit`, request attribution, `RequestIDMiddleware`, `shared.log_sanitize`, ECS logging | Strict mutation evidence uses the existing event/vocabulary/store. Operational logs carry safe IDs, operation/role/outcome, and request correlation only. |

`list_events_for_organizer` has no live caller outside its exports; it is not a
second listing contract. The mock-heavy `test_organizer_access.py` is also not
proof that ORM role joins, soft-deletion, concurrency, or service-layer denial
work.

## Surface and service coverage

The policy change is complete only when all event-bearing surfaces ask the same
service policy. A direct owner comparison remains valid only where this note
explicitly says owner-only.

- HTML and legacy JSON: `ctf.views._access`, every `admin_*` view, and legacy
  event/challenge/hint/file/participant/range/scoreboard/notification routes use
  capability-aware resolvers. Do not patch dozens of comparisons with another
  locally named boolean.
- Canonical v1 API: organizer event/detail/lifecycle/content/challenge/
  attachment/participant/range/scoreboard/insight/transfer/notification/page/
  webhook endpoints retain `CTF_ORGANIZER_PERMISSIONS` and exact read/write
  scope, then authorize the resource operation. `ctf:event:write` alone never
  grants another organizer's event.
- Service defense in depth: replace operational uses of
  `assert_actor_owns_event` with the one raising capability assertion in
  challenge, flag, hint, attachment, prerequisite, content, participant,
  scoring/bracket/award/team, event, notification, transfer, and range command
  services. View-only checks are insufficient for internal and future callers.
- Organizer-sensitive reads: hidden/frozen scoreboards, participant solve
  history/timelines, attachment access, analytics, task history, and exports
  recognize the appropriate co-organizer capability without widening public or
  participant visibility.
- Realtime and notifications: subscription authorization may continue to admit
  the currently supported participants and bounded staff, including the new
  organizer row. Organizer-directed operational recipients are the owner plus
  live organizer-role assignments, de-duplicated at publish time; moderator and
  judge recipient behavior remains unchanged. Do not conflate notification
  `created_by`/sender attribution with the recipient set or event ownership.
- Background execution: scheduled automatic transitions remain trusted system
  operations reached only from durable task state. Manual enqueue, run-now,
  cleanup controls, recovery, and destructive commands are authorized and
  request-attributed at acceptance. A worker must not accept a caller-supplied
  role or skip the existing event/state/range gates.

## Audit and destructive-operation boundary

Assignment, re-role, revocation, transfer, soft delete, force-delete acceptance
and outcome, cancellation, destructive lifecycle transitions, manual cleanup
controls, and equivalent accepted commands require durable audit evidence.
Reuse generic `CREATE`, `UPDATE`, `DELETE`, `CANCEL`, and existing lifecycle
actions with bounded CTF contexts; do not invent a second audit model or action
taxonomy. Record stable event/assignment/target/actor IDs, old/new role or
owner, action, outcome/counts, and trusted request attribution. Never record
email, event/challenge content, confirmation text, request bodies, headers,
cookies, tokens, flags, credentials, presigned URLs, or provider errors.

Authority mutations and database-only lifecycle changes write
`shared.audit(..., strict=True)` inside the same transaction, so audit failure
rolls back the mutation. External range/S3/email work must not run inside a
database transaction. For force deletion, write a strict accepted-intent record
before external effects and a bounded completion/failure outcome afterwards.
Do not hard-delete the event and its reconciliation identifiers while any
required external range or object cleanup failed; leave recoverable state for a
safe retry. Audit cannot make an irreversible provider side effect
transactional.

Soft delete retains its existing confirmation/UI semantics, authorization,
task cancellation, and audit. Force delete retains exact-name confirmation,
all-object lookup, CMS-owned range destruction, and S3 cleanup, but the service
itself must authorize the actor; the current view-only owner check is not a
service boundary. Co-organizer access must not weaken these safeguards.

## Cross-cutting security and whole-repository layers

1. **Identity and account admission.** Existing OIDC/Identity Platform issuer,
   audience/authorized-party, subject, verified-email, bind-once, and organizer
   grant reconciliation produce an active Django user. `CTFAccountBoundaryMiddleware`
   and `CTFAccountWebSocketBoundary` keep temporary participant accounts away
   from organizer surfaces. Event code parses no provider claims and never
   auto-promotes an assignment target.
2. **HTTP/session/token admission.** Bearer credentials fail closed before
   session fallback; token expiry/revocation and `created_by` binding, active
   actor resolution, organizer role, endpoint scope, session CSRF, and explicit
   serializer shape all pass before event policy. Owner/co-organizer status does
   not mint, widen, or preserve token scopes.
3. **Event authorization.** One live, fail-closed event capability check runs at
   the HTTP boundary and again in every interactive service before effects.
   Owner-only topology operations recheck exact ownership under the event lock.
   Missing, deleted, unrelated, removed, unknown-role, and unknown-operation
   cases deny without exposing owner or roster details.
4. **Domain and cross-domain validation.** Existing event/challenge/content/
   participant/team/scoring/lifecycle validators still run. Range commands also
   pass CTF participant/event provenance, CMS user/range ownership and source,
   Engine lifecycle/operation, capacity/admission, remote-access generation,
   and provider validation. Event co-organization never bypasses or rewrites a
   participant's range owner.
5. **Persistence and concurrency.** Model full-clean, role choice, DB role
   check, active-row uniqueness, non-null/protected owner, `transaction.atomic`,
   stable lock order, and `select_for_update` enforce the durable authority
   invariants. Soft-deleted assignments grant nothing.
6. **Realtime.** `AllowedHostsOriginValidator`, session authentication, the CTF
   WebSocket account boundary, topic shape validation, notification-type
   registry, live subscription authorization, recipient-scoped rows, expiry,
   and bounded replay remain in force. Future publishes derive organizer
   recipients from current live assignments, so removal stops future delivery.
7. **Errors, privacy, and observability.** Canonical v1 failures use
   `{"error":{"code","message","details?","request_id?"}}`; legacy flat
   errors stay legacy only. Responses and logs never expose SQL, constraint
   text, owner IDs, role rosters, raw exceptions, secrets, or provider payloads.
   Audit is durable evidence; sanitized correlated logs are operational
   diagnostics, not a duplicate audit stream.
8. **Configuration and secret shapes.** No setting, feature flag, environment
   variable, provider claim mapping, `config/env-manifest.json` field,
   `.shifter.yaml` key, Terraform/Helm/Kubernetes value, or secret-manager entry
   is needed. Event authorization is code/data policy, not deployment-configured
   policy. Existing encrypted/hashed/reference-only secret shapes are unchanged.
9. **OS, process, cloud, and task exposure.** No role, email, token, cookie,
   confirmation value, or secret enters environment, process argv, shell
   commands, temp files, provider labels, metrics, static bundles, or task
   payloads. AWS/GCP/IAM/network behavior is unchanged; co-organizers call the
   same provider-neutral CTF -> CMS -> Engine services.
10. **Published contract and repository gates.** Runtime serializers/OpenAPI
    remain authoritative; regenerate `openapi/v1.json` and generated frontend
    types rather than hand-copying DTOs. Preserve import/layer/FK checks,
    migration drift, OpenAPI drift/breaking checks, Ruff, Django/pytest,
    frontend lint/type/Vitest/axe/build, and `adr_guard`.

## Extensibility seam

The extension seam is an explicit event-operation parameter passed through one
resolver/assertion into one role map. A later bounded staff role or event
operation adds one closed vocabulary value and one intentional role mapping;
callers do not add another owner boolean, query `CTFEventStaff` directly, or
reimplement role semantics. Full organizers receive the maintained set of
operational capabilities, while owner-only capabilities remain a separately
named set. Unknown values remain denied.

The read seam is one owner-or-live-organizer queryset plus a server-derived
access projection (`access_role` and advisory capabilities) shared by event
summary/detail responses. A later UI surface consumes that projection and the
same policy vocabulary; it does not compare hard-coded role strings or maintain
a frontend permission matrix. The notification seam is one live organizer
recipient projection, distinct from sender/owner attribution.

## Required evidence, gotchas, and anti-patterns

- Exercise real database/service/API behavior for owner, co-organizer,
  moderator, judge, unrelated organizer, participant/standard user, removed
  organizer, and canonical-owner protection. Cover session and appropriately
  scoped/under-scoped API tokens.
- Cover organizer listings/status filters without duplicates; every documented
  admin surface; hidden/frozen reads; HTML and v1 errors; realtime subscribe,
  publish, replay, and post-removal future delivery; and background command
  acceptance/system execution.
- Cover concurrent assign/re-role/revoke/transfer, invalid persisted roles,
  owner-target rejection, transfer preserving the previous owner's access,
  strict-audit rollback, safe actor attribution, destructive confirmation,
  partial external cleanup, and bounded audit/log content.
- Do not bulk-replace `created_by` blindly. Creation ownership, canonical
  notification sender/fallback, audit attribution, and owner-only topology
  operations still mean the canonical owner; operational authorization and
  recipient selection do not.
- Do not treat `CTF Organizer`, Django staff/superuser, API-token scope,
  workspace owner/admin, CTF team captain, notification subscription, UI
  visibility, cached capability hints, or `created_by` on a notification as
  interchangeable authority.
- Do not grant co-organizers by copying the owner ID, changing participant/range
  owners, sharing an owner account/token, adding an email allowlist, or writing
  role data into JSON/config/task metadata.
- Do not add a second role enum/map, ownership helper, serializer DTO, exception
  hierarchy, audit table/writer, logging vocabulary, frontend fetch client,
  query cache, WebSocket consumer, task runner, or provider branch.
- Do not let owner-only default arguments, omitted capability parameters,
  truthy unknown roles, or a role wildcard make a new call site accidentally
  owner-only or accidentally world-writable.

## Non-goals and implementation boundaries

- No implementation in this note and no formal Ground Control requirement.
- No redesign of global organizer provisioning, identity-provider claims,
  Django admin, API-token scopes, participant identity/accounts, CTF teams,
  workspace tenancy, CMS/Engine range ownership, or cloud IAM.
- No invitation flow for users without an existing active platform organizer
  account, no custom per-user capability overrides, no multiple canonical
  owners, no anonymous/event-public administration, and no self-service
  organizer grant/revoke.
- No new authorization framework, generic RBAC product, repository layer,
  event bus, workflow engine, notification system, audit store, settings flag,
  secret, worker, provider adapter, or infrastructure component.
- No weakening of moderator/judge permissions, participant scoreboard/content
  visibility, event state transitions, destructive confirmations, range safety,
  validation, secret redaction, or v1 compatibility under cover of adding
  co-organizers.
