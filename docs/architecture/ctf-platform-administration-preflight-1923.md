# CTF Platform Administration Preflight (#1923)

Status: pre-implementation guidance

Date: 2026-08-14

Issue: GitHub #1923, "Allow platform administrators to see and administer all
CTF events"

Requirement: none. The issue title, body, and acceptance criteria are the
shipping contract.

This note fixes the authority, tenancy, audit, API, and lifecycle boundaries
for #1923. It does not implement the issue or prescribe an implementation
sequence.

## Decision and scope boundary

The existing, verified platform-root authority is an active Django user with
`is_superuser=True`. CTF administration may use that authority as an
orthogonal override for an existing event. It must not turn the user into a CTF
organizer, event owner, or delegated event-staff member, and it must not derive
authority from an email, `is_staff`, Django model permissions, an auth group,
an organization/workspace role, a provider claim, an API-token scope, or a
client capability. Marked temporary CTF accounts remain deny-authoritative even
if their flags or groups drift.

`CTFEvent.created_by` remains the event owner. `CTFEventStaff` remains the
bounded delegation model: moderator grants participants/notifications and
judge grants awards/submissions. It is not a full co-organizer role and this
issue must not broaden it to event configuration, challenges, scoring,
lifecycle, staff management, or destructive actions.

Event administration authority is resolved for a named operation at the CTF
service boundary and returns a closed, server-derived authority source:

| Source | Authority | Guardrail |
| --- | --- | --- |
| `owner` | `event.created_by_id == actor.pk` | Full incumbent owner policy. |
| `event_staff` | A live staff row grants the requested existing capability | Never grants an unnamed or owner-only operation. |
| `platform_admin` | Active, non-temporary `is_superuser` fallback | Full administration of an existing event without changing ownership or staff. |

Resolution uses least authority: owner first, then a staff capability that
actually covers the operation, then the platform override. Thus a superuser
who owns an event acts as owner; a superuser assigned as judge acts as judge
for a submissions operation; and the same user acts as platform administrator
only for an operation those event relationships do not grant. The authority
source is derived per operation, never accepted from a request or cached as a
user/event role.

The policy must be service-owned and reused by every event-derived resource
resolver (event, challenge, participant, file, flag, prerequisite,
notification, webhook, staff assignment, scoring, range, content, task, and
award). Widening only the event list or the DRF top-level permission leaves the
direct `created_by` checks and service mutators inconsistent and is not
acceptable. Canonical `/api/v1/ctf/` views, any retained legacy HTML/JSON
callables, background command entry points, and tests must call the same
service policy; HTTP wrappers may translate its opaque denial but do not own a
second policy.

Pure platform-admin authority applies to existing-event reads and necessary
administrative/lifecycle mutations. It does not authorize event creation:
`POST /events/` currently makes its actor `created_by`, which would conflate the
override with ownership. A platform administrator who independently holds the
organizer role may create an event under ordinary organizer authority and
become its owner. Ownership transfer, impersonation, and a caller-selected
owner are outside #1923.

## Tenancy boundary

ADR-046-R7 deliberately keeps CTF events, teams, and participants in a
deployment-global membership model. `CTFEvent` has no organization or
workspace binding to preserve. Therefore #1923 must not add a tenant foreign
key, infer a tenant from the event owner, selected workspace, participant
range, organization membership, or UI context, or treat a workspace/org role
as CTF authority.

The cross-tenant acceptance case is composition evidence:

- an organization admin, workspace owner/admin, and unrelated CTF organizer
  gain no CTF access merely because of tenant authority;
- delegated event staff retain only their existing event capabilities; and
- the platform superuser is deployment-global and may administer an existing
  CTF event regardless of the owner or the owner's tenant memberships.

Adding real tenant scope to CTF events is a separate persistence and migration
decision requiring its own ADR. It cannot be smuggled into this authority
change.

## Read, API, and UI contract

The canonical organizer surface remains the SPA over `/api/v1/ctf/`; route and
navigation guards are advisory. The server must expose one advisory
"can administer CTF" result for organizer-or-platform-admin admission rather
than changing `is_ctf_organizer` or scattering
`is_ctf_organizer || is_superuser` through bootstrap, routes, navigation, and
components. Resource endpoints always repeat authentication, scope, actor, and
object authorization.

The event discovery query is authority-aware:

- platform override: all live events through the default manager, including
  archived events but excluding soft-deleted tombstones;
- ordinary owner: owned events;
- delegated staff: events with a live assignment, deduplicated from owned
  events.

The projection shows status, a bounded owner object, and the server-derived
access source/capabilities. Reuse one typed owner projection (stable user id and
display name are sufficient); do not serialize the Django `User`, provider
subject, groups, role facts, or internal identity payload. A bounded typed
query serializer owns search, status, owner, page, and ordering validation.
Search/order fields are an allowlist, status uses `EventStatus`, query length
and page size are capped, ordering is deterministic, the owner join is eager,
and owner/staff unions cannot duplicate rows or create an N+1 query.

ADR-040 governs the published v1 shape. Keep the existing `{"events": [...]}`
envelope unless the compatibility gate authorizes an evolution; do not
silently replace it with DRF's `results` envelope or change the default result
semantics for existing organizer consumers. The newly admitted platform-admin
path must still be bounded when pagination inputs are omitted, using the
canonical page-size bound while retaining the v1 envelope; principal-specific
behavior and any optional page metadata must be described truthfully in the
runtime contract. Optional query parameters and optional response fields flow
through runtime serializers/annotations, committed OpenAPI, and generated
TypeScript. The SPA uses the existing CTF API client, TanStack Query, URL-backed
search/page state, and generated types rather than direct `fetch` or copied
DTOs.

The UI must display owner and status on the list and a conspicuous access
context on detail/mutation surfaces. Controls are derived from server-projected
capabilities for usability only. A platform-admin banner cannot authorize a
request, and hiding a control cannot replace an endpoint check. Assigned event
staff must not be led into owner-only pages merely because their event now
appears in discovery.

## Mutation and audit contract

All existing domain gates remain after platform authorization: explicit DRF
serializers, service mutable-field allowlists, model `clean()`/`full_clean()`,
database constraints, row locks/transactions, event and challenge state
machines, participant/scoring rules, content/upload validation, range/CMS
bridges, rate limits, and provider lifecycle safeguards. A platform override
changes who may request an operation, never whether the operation is valid.

Every successful interactive mutation performed with `platform_admin`
authority against another user's event must produce a durable `shared.audit`
record. The bounded state includes event id, operation, effective actor user id,
and `authority_source=platform_admin`, plus changed field names or safe outcome
metadata as appropriate; it does not include event content, participant data,
credentials, flags, solutions, webhook secrets, signed URLs, provider payloads,
or raw exception text. Owner and event-staff mutations should use the same
closed authority-source vocabulary when that workflow is audited so records
remain comparable.

Request attribution is captured at the HTTP boundary with
`shared.audit.get_actor_from_request`, `get_client_ip`, and `get_request_id`
before a legacy wrapper can replace `request.user`. A session records the user;
an API-token call records the token as `APIKEY` and separately records the
effective owner user id whose live authority was evaluated. Exact token scopes
remain application admission only and never become event authority.

For a database-only mutation, the write, locked reauthorization where the
incumbent workflow requires it, and strict audit event belong in one
transaction; audit failure rolls the mutation back. For non-rollbackable work
(range/provider teardown or provisioning, notification/webhook delivery,
storage/content operations), do not hold a database transaction across the
external call or claim false atomicity. Strictly persist bounded override
intent before the first side effect, then record a bounded completion or
failure outcome correlated by request/operation id. Reuse the workflow's
idempotency, outbox/reconciler, and lifecycle status where present rather than
adding a CTF-admin retry engine.

Reads are not audited row-by-row: that would create write amplification and a
feed changed merely by viewing it. Existing denied-access/security audit policy
and mutation audit are the relevant evidence surfaces.

Destructive actions retain the incumbent soft-delete versus force-delete
distinction, lifecycle eligibility, range teardown/recovery behavior, explicit
confirmation, and type-the-event-name force-delete check. Platform authority
must never bypass them or expose soft-deleted rows through ordinary list/detail
queries.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail for #1923 |
| --- | --- | --- |
| Verified platform authority | `config/_oidc_settings.py`; `config/bootstrap_admin.py`; `shared/verified_identity.py`; OIDC/Identity Platform validation | Let the existing typed CSV binding select bootstrap superusers at verified login, then read persisted `is_superuser`. CTF never re-reads the email list or provider claims. |
| CTF role/account boundary | `shared/auth.py`; `config/organizer_authority.py`; `config/middleware.py::CTFAccountBoundaryMiddleware` | Keep organizer membership separate and temporary-account origin deny-authoritative. |
| Session/token admission | `ctf/api/_base.py`; `shared/api/principals.py`; `shared/api_tokens/authentication.py`; `shared/api_tokens/scopes.py` | Active actor, bearer-first fail closed, exact read/write scope, session CSRF, no wildcard or authority-by-scope. |
| Event authority | `ctf/services/authorization.py`; `ctf/services/event/staff.py`; `ctf/api/organizer/_base.py` | Consolidate the incumbent owner/capability checks at the service boundary; no parallel controller predicates. |
| Ownership/delegation persistence | `ctf/models/event.py::CTFEvent`; `CTFEventStaff`; soft-delete managers | Do not change owner, synthesize staff, add a global-role row, or use `all_objects` outside explicit recovery/deletion. |
| Reads and shapes | `ctf/services/event/_queries.py`; the duplicate `_crud.py::list_events_for_organizer`; `ctf/api/serializers/organizer.py`; organizer event API | Collapse/delegate the duplicate exports to one authority-aware query and typed query/owner/access projections; no second list repository or model serialization. |
| Validation/lifecycle | `ctf/services/event`; `ctf/services/challenge`; `ctf/enums.py`; model validation and constraints | Platform authority does not bypass mutable-field allowlists, state machines, locks, or domain validation. |
| Cross-domain operations | `ctf/bridges.py`; public CMS/Engine service facades; existing range/content workflows | Preserve CTF-to-service boundaries, idempotency, provider-neutral state, and external-operation recovery. |
| Audit/observability | `shared/audit/*`; `ctf/services/audit.py`; `RequestIDMiddleware`; `shared/log_sanitize.py`; ADR-045/048 patterns | One durable audit store, trusted attribution, strict policy, safe bounded state, request correlation. No `management.ActivityLog` or new CTF audit table. |
| HTTP errors | `ctf/api/_base.py::_CtfApiError`; `shared/api/errors.py`; `ctf.exceptions` | One sanitized request-id envelope; map domain errors once and keep missing/unauthorized targets opaque. |
| SPA contract | `config/api_bootstrap.py`; `frontend/src/app/nav.ts`; `router.tsx`; `features/ctf/routes.ts`; `api/ctfAdmin.ts`; generated `api/schema.d.ts`/`types.ts` | One advisory gate, one client/cache, generated DTOs, and no frontend authority logic. |
| Destructive UX | `frontend/src/components/confirm-dialog.tsx`; CTF `EventDetailPage` and `EventLifecycleCard` | Preserve explicit confirmations, typed-name force delete, accessible focus, and server-side state checks. |
| Enforcement/tests | `.importlinter`; layer checks; `scripts/adr_guard/adr_guard.py`; CTF API/service/SPA tests | Preserve architectural boundaries and prove the full authority/credential/tenant matrix. |

## Cross-cutting layers the design must pass

1. **Identity validation.** Verified issuer/subject/email and literal
   `email_verified` checks bind the Django user before bootstrap-admin policy
   persists `is_superuser`. `config/_oidc_settings.py` owns the existing typed
   `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` CSV binding. CTF code reads the
   persisted flag; it does not re-open email, environment, or provider
   validation.
2. **Authentication and actor shape.** `ApiTokenAuthentication` remains before
   session authentication and fails closed on a bad bearer. The represented
   user must be authenticated and active; marked temporary accounts cannot use
   platform override. Unsafe session requests retain CSRF.
3. **Application scope and top-level admission.** Token calls retain exact
   `ctf:event:read`/`ctf:event:write` gates. The CTF admin surface admits an
   ordinary organizer or qualifying platform administrator without redefining
   either role. Scopes and SPA bootstrap stay advisory/additive.
4. **Per-object policy.** A service resolver takes actor, event, and explicit
   operation/capability, then returns the closed authority source or one opaque
   denial. Every nested resource resolves its event before returning or
   mutating data.
5. **Payload and domain validation.** DRF serializers shape HTTP/query input;
   service allowlists and validators, model validation, database constraints,
   locks, and lifecycle/range/content policies enforce domain invariants. The
   client may mirror hints only.
6. **Tenant composition.** There is no CTF tenant shape to validate today.
   Workspace/organization context grants nothing; platform superuser remains
   deployment-global under ADR-046-R7. A future event-tenant binding enters at
   the central resolver, not in controllers.
7. **Audit and logging.** Trusted credential, source IP, user agent, and request
   id are captured once; platform-override mutations are strict-audited with
   safe identifiers and outcomes. ECS logs use sanitizers and never replace
   durable audit.
8. **Error envelope and privacy.** Domain failures map to the shared
   `error.code/message/details?/request_id?` envelope. No owner identity,
   provider claim, permission fact, SQL/provider exception, credential, or
   sensitive event data leaks through errors or logs.
9. **API publication and browser boundary.** Runtime serializers/permissions
   generate OpenAPI; generated TypeScript feeds the existing same-origin SPA
   client. Route/nav/access displays are advisory, output is escaped, and
   destructive dialogs remain accessible.
10. **Config, secrets, and OS exposure.** #1923 needs no new environment
    variable, secret binding, Terraform/Kubernetes value, cloud credential,
    process, shell command, or subprocess argument. The existing bootstrap
    authority configuration is consumed only by its identity adapter. Do not
    put an admin marker, claimed authority/tenant, or token in URL paths, query
    strings, command argv, environment, logs, or client storage as a substitute
    for server-derived authority. Bounded owner/search/page query filters are
    data selection only and never authority inputs.

## Extensibility seam

The required seam is the service-owned event-administration decision,
parameterized by actor, event, and an explicit operation/capability, returning
an authority source plus the existing bounded capabilities. The list query and
detail projection consume the same policy. This lets a later event operation
or staff capability extend one closed matrix, and lets a separately accepted
future CTF tenant binding add an event-scope check in one place, without
re-editing every controller, legacy view, serializer, or component.

Do not parameterize this seam with caller-supplied authority, tenant id, owner
id, `is_admin`, or arbitrary permission strings. Closed server-owned operation
values are the extension point.

## Whole-repository scope

The implementation must evaluate these surfaces together:

- ADR-001, ADR-013, ADR-029, ADR-040, ADR-045, ADR-046-R7, ADR-048,
  ADR-052, and the CTF SPA/API preflights;
- identity/bootstrap/role/account-boundary configuration under `config/` and
  `shared/auth.py`/`shared/verified_identity.py`;
- CTF DRF permissions, organizer endpoints/serializers, legacy access helpers,
  URL routing, services, bridges, models/managers, enums, exceptions, audit,
  range/content/scoring/notification workflows, and scheduled tasks;
- shared token authentication/scopes, audit, error envelope, request
  attribution, logging sanitation, API schema generation, and the committed
  OpenAPI contract;
- SPA bootstrap, central nav/router, CTF admin pages, generated API types,
  query cache/client, access-context presentation, and confirmation dialogs;
- CTF service/API/token/frontend tests plus workspace/organization fixtures for
  negative tenant-authority composition; and
- import/layer enforcement, ADR guard, API compatibility/drift checks,
  Django checks, and frontend lint/type/test/build/accessibility gates.

No environment manifest, workflow, deployment, host, Terraform, Kubernetes,
cloud-provider, or OS process surface should change. If implementation finds
that one is needed, it has crossed this preflight boundary and requires renewed
architecture review.

## Gotchas and anti-patterns

- Do not change `is_ctf_organizer`, add superusers to the CTF Organizer group,
  create an `admin` event-staff role, or use `is_staff`/model permissions.
- Do not check a bootstrap-admin email, provider group, configured allowlist, or
  client `is_superuser` flag in a CTF endpoint.
- Do not widen `CTF_ORGANIZER_PERMISSIONS` and stop; direct ownership checks in
  nested API views, legacy views, staff services, and content mutators must not
  remain divergent.
- Do not treat token scope as object authority, lose API-token attribution by
  rewriting `request.user`, or let an invalid bearer fall through to session.
- Do not let a temporary participant account gain admin access through flag or
  group drift merely because all `/api/v1/ctf/` paths pass the account-boundary
  middleware's path admission.
- Do not conflate platform administrator, event owner, organizer, event staff,
  organization admin, workspace owner/admin, selected workspace, or UX mode.
- Do not change `created_by`, create an event on pure override authority, infer
  ownership from audit, or allow a caller-selected owner/authority source.
- Do not add organization/workspace columns to CTF models or infer an event
  tenant from its owner or ranges.
- Do not return all events and filter in React, serialize raw users, expose
  provider claims/groups, implement arbitrary ORM search/order, or introduce a
  second list repository/DTO.
- Do not update only one of `_queries.get_organizer_events` and
  `_crud.list_events_for_organizer`; their current duplicate exports must not
  become two global-access policies.
- Do not use the default `all_objects` manager for normal global visibility;
  soft-deleted events remain recovery/destruction-only.
- Do not bypass state machines, rate limits, transactions, row locks, model
  constraints, upload/content inspection, range safeguards, confirmations, or
  force-delete name matching because the actor is platform administrator.
- Do not create a second audit table, exception hierarchy, error envelope,
  authorization cache, retry engine, frontend permission matrix, or workflow.
- Do not log/audit payload values, participant PII, flags, solutions,
  credentials, webhook secrets, signed URLs, headers, provider output, or raw
  exceptions, and do not claim atomic audit for an external side effect.
- Do not hand-edit OpenAPI/generated TypeScript or silently change the v1 list
  envelope/pagination semantics.

## Non-goals and implementation boundaries

- No implementation, endpoint, serializer, service, model, migration, UI, test,
  or deployment change in this preflight.
- No new platform role, self-service admin grant, organizer authority source,
  event-staff role/capability, event ownership transfer, impersonation, or
  caller-selected owner.
- No CTF tenant binding, organization/workspace inheritance, per-tenant
  platform administrator, or selected-workspace scoping.
- No event creation by pure platform override and no expansion of participant,
  public scoreboard, or Django admin semantics.
- No retirement of retained legacy CTF routes or broad API consolidation beyond
  the authorization consistency required by #1923.
- No change to event/challenge/scoring/range/notification/content lifecycle,
  validation, persistence, provider, or destructive-action semantics.
- No new config, secret, token scope, environment binding, infrastructure,
  background queue, audit store, logging pipeline, or exception family.

## Required proof for the eventual implementation

Evidence must cover service policy, canonical API, token/session behavior, and
SPA advisory behavior for: active non-temporary platform superuser; owner;
moderator and judge with their exact capabilities; unrelated organizer;
ordinary authenticated user; participant/temporary account (including
privilege drift); inactive superuser; `is_staff`/model-permission-only user;
and organization/workspace roles that must not widen CTF access.

It must also cover superuser token read/write with exact and missing scopes,
bad-bearer fail-closed behavior, session CSRF, owner/staff/platform-admin
authority precedence, unchanged `created_by`, archived versus soft-deleted
visibility, bounded search/status/owner/pagination with deterministic no-N+1
results, nested resource and mutation parity, lifecycle/destructive safeguards,
strict audit failure for database-only changes, intent/outcome audit for
external work, token plus effective-user attribution, opaque errors, generated
contract drift, access-context UI, confirmations, and the negative tenant-role
composition described above.
