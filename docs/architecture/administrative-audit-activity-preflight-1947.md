# Administrative audit/activity preflight (#1947)

Status: pre-implementation guidance

Date: 2026-08-11

Requirements: PLAT-240 (implements), PLAT-241 (constrains)

This note fixes the repository-wide boundaries for the administrator audit and
activity-history surface. It is not an implementation plan and adds no runtime
route, serializer, query, component, schema, migration, event, or cloud
behavior.

## Decision and scope boundary

PLAT-240 extends the existing cross-cutting audit read capability; it does not
create an administration-owned activity system:

- `shared.audit` remains the only event contract, vocabulary, attribution,
  failure-policy, and writer boundary.
- `shared.models.AuditLog` and `shared_auditlog` remain the only durable audit
  model and table. `shared.audit_adapter` remains the persistence adapter.
- `shared.api.audit` and `/api/v1/audit/` remain the canonical read API. Do not
  add `/api/v1/administer/audit/`, a frontend BFF, or a second serializer-backed
  copy of the records merely to match the SPA route name.
- The SPA page is a read-only consumer in the existing Administer shell. Its
  client route belongs at `/administer/audit`, not below a selected workspace.
  The `audit` placeholder currently in `WORKSPACE_SURFACES` must not become the
  real surface in place.
- The existing `ADMINISTER_SPA_ENABLED` plus platform-SPA flag gates the page.
  PLAT-240 adds no setting, environment binding, secret, provider switch, or
  cloud adapter.

The placement decision is security-significant. ADR-046-R7 explicitly keeps
the durable audit store deployment-global. `AuditLog` has generic integer
`entity_id` and `actor_id` fields, not an authoritative organization/workspace
scope on every row. Inferring a tenant from an entity id, current ORM relation,
`context`, or `previous_state`/`new_state` would be incomplete, mutable, and an
authorization leak. A workspace UUID in the browser route, query key, or API
request must therefore neither filter nor authorize this surface.

The accepted ADR-045 authorization contract remains staff/superuser Django
session only. Organization-admin membership, workspace owner/admin role,
Django model permissions, API-token scopes, provider groups, cloud IAM, nav
visibility, and the selected workspace do not grant audit access. A future
tenant-scoped audit product needs a separate decision and an explicit scope in
the event contract at emission time; it must not reconstruct scope from old
rows.

No new ADR is required while the implementation stays within ADR-029, ADR-040,
ADR-045, ADR-046-R7, and the decisions above. Changing audit ownership,
authorization, durability, retention, API-token access, or tenant scope does
require ADR reconciliation.

## Read contract

The current endpoint already supplies list/retrieve, immutable serialization,
page-number pagination, and exact filters. PLAT-240 should harden and publish
that one contract rather than add another query path.

- `action` is the existing audit event-type dimension. `entity_type` plus
  `entity_id` is the entity dimension; `actor_type` plus nullable `actor_id` is
  the actor dimension. Do not introduce an overlapping `event_type`, generic
  admin-role, activity-category, or frontend-only taxonomy. Authentication,
  membership, invitation, user-lifecycle, and policy events are combinations
  of the canonical action/entity vocabulary emitted by their owning workflows.
- Preserve the existing filter names: `entity_type`, `entity_id`, `action`,
  `actor_type`, `actor_id`, `request_id`, `from_date`, and `to_date`. Validate
  them with one explicit DRF query serializer before constructing the queryset.
  IDs must parse as integers (including historical sentinel entity id `0`),
  timestamps must be timezone-aware ISO-8601 values, and `from_date` must not be
  later than `to_date`. Invalid input returns the shared 400 envelope; it is
  never ignored, silently truncated, or allowed to become an ORM/500 error.
- Audit vocabulary is append-only but historical rows can contain retired
  strings. Response and exact-filter fields therefore remain bounded strings,
  not closed serializer choices that make old evidence unreadable. The active
  `AuditAction`, `AuditEntityType`, and `AuditActorType` values remain the only
  vocabulary for new emitters.
- Opt out of the global `SearchFilter` and `OrderingFilter` unless the endpoint
  explicitly defines truthful, indexed fields for them. The generated contract
  must not advertise inert `search`/`ordering` parameters. Do not add an
  unindexed free-text scan across `context` or JSON state just to satisfy a
  search-box design; structured actor/entity/time/action filters are the
  authoritative search surface.
- Keep pagination on the canonical DRF page shape for v1 compatibility and use
  deterministic `-timestamp, -id` ordering. The existing actor, entity,
  timestamp, action, and request-id indexes are the first query incumbents.
  Add an index only from representative PostgreSQL query-plan evidence; do not
  index arbitrary JSON/context keys or create provider-specific storage.
- The wire model remains the generated OpenAPI `AuditLog` contract. A v1 field
  must not be removed, narrowed, or retyped for the SPA. Regenerate
  `openapi/v1.json` and `frontend/src/api/schema.d.ts`; frontend code re-exports
  generated types from `frontend/src/api/types.ts` rather than hand-copying an
  audit DTO or validator.

Audit `previous_state`, `new_state`, and `context` are durable evidence, not
current entity state. The SPA may render them only as escaped text/data and
must tolerate missing fields, unknown keys/vocabulary, deleted actors/entities,
and historical shapes. It must not use `dangerouslySetInnerHTML`, infer policy
from a state key, mutate a row, or resolve every generic entity by importing or
calling all owning domains. Any optional current actor label is non-authoritative
enrichment: the stable evidence remains `actor_type`/`actor_id`, resolution must
be page-batched rather than N+1, and a deleted/renamed user must not rewrite
history.

The audit-event contract requires bounded, JSON-safe summaries and prohibits
tokens, cookies, credentials, raw headers, and provider payloads. PLAT-240 must
not compensate for a violating emitter with a second client-side redaction
policy. Fix unsafe data at the canonical emitter/shared-audit boundary and keep
tests proving the sensitive field never enters the durable row. The UI should
show the minimum evidence needed by default and place verbose state/context in
an explicit detail disclosure.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Event contract and writes | `shared/audit/{events,vocabulary,attribution,policy,port}.py`; `shared.audit_adapter` | Read existing rows only. No new event bus, writer, action enum, attribution helper, strict/best-effort policy, or failure hierarchy. |
| Persistence and retention | `shared.models.AuditLog`; its current indexes; `shared.management.commands.audit_archive`; `shared.admin.AuditLogAdmin` | No second table, materialized activity ledger, cross-domain FK, mutating API, archive reader, or browser cache as evidence. |
| Read API | `shared.api.audit`; `shared.api.urls`; ADR-045-R3 | Harden the existing list/retrieve endpoint and permission behavior. No parallel Administer API. |
| Browser authentication | `ApiTokenAuthentication` then `SessionAuthentication`; `shared.api.permissions.IsStaffSession`; existing Administer/workspace-console views | Bearer parsing is first and fail-closed; valid tokens are rejected and invalid bearer credentials cannot fall through to a valid session. Preserve denied-read auditing without duplicating a second staff-authority rule. |
| HTTP validation/errors | Explicit DRF serializers; `config._drf_settings`; `shared.api.errors`; `shared.api.schema.ApiErrorSerializer` | One typed query shape and the standard request-id error envelope. No ad hoc `request.query_params` coercion, `JsonResponse`, or new exception tree. |
| API publication | `config.api_urls`; `shared.api.contract`; `openapi/v1.json`; generated `frontend/src/api/schema.d.ts` and re-exports in `types.ts` | Runtime serializers are authoritative; preserve ADR-040 v1 compatibility and the OpenAPI drift/breaking-change gates. |
| SPA data access | `frontend/src/api/client.ts`; `queryClient.ts`; `types.ts`; Administer API modules and `UsersListPage` URL-filter pattern | One same-origin session client, TanStack Query cache, generated types, URL-backed filters, bounded retry, and no direct component `fetch`. |
| SPA shell and UI | `frontend/src/router.tsx`; `features/administer/routes.ts`; `app/nav.ts`; `PageHeader`, `Alert`, `Skeleton`, `Table`, `Input`, `Select`, and accessibility test helpers | Extend the existing Administer shell and central nav/router. No second shell, router, table system, state store, or design language. |
| Observability | `RequestIDMiddleware`; `config.logging.ECSFormatter`; `shared.log_sanitize`; audit-health tracking | Correlate safe counts/outcomes by request id. Never log filters containing personal data, JSON state/context, headers, tokens, SQL, or provider exceptions. |
| Architecture boundaries | ADR-001/045/046; `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `check_model_fks`; `adr_guard` | `shared` keeps owning the cross-cutting read. Do not move it into `management` or make `shared` import product-domain models for enrichment. |

`management.models.ActivityLog` and `management.services.log_activity` are
historical/deprecated compatibility surfaces. They are not a source, fallback,
analytics cache, or migration target for PLAT-240.

## Cross-cutting layers the design must pass

1. **Identity and account admission.** Existing OIDC/Identity Platform issuer,
   audience/authorized-party, subject, and verified-email validation binds the
   Django session. PLAT-240 parses no claims and adds no group mapping. The
   `CTFAccountBoundaryMiddleware` continues to block temporary participant
   accounts from this API and page; neither path joins its exact allowlist.
2. **Browser/session and token authentication.** The SPA uses the same-origin
   session cookie through `apiFetch`; it stores or sends no platform bearer
   token. The API authentication order is `ApiTokenAuthentication` then
   `SessionAuthentication`, matching the Administer incumbents: invalid bearers
   fail closed before session fallback, valid token principals reach the
   session-only permission and are denied, and the existing session remains the
   only accepted credential.
3. **Authorization.** Preserve ADR-045's staff/superuser session gate and denied
   read audit. Do not weaken it to any authenticated user or organization admin,
   and do not add an audit token scope. Successful ordinary reads should not
   emit audit rows: doing so creates write amplification and a feed that changes
   merely by being viewed.
4. **Query and response shape.** An explicit DRF serializer validates all query
   values and cross-field time rules; canonical pagination bounds rows; fixed
   ordering stabilizes pages. The response serializer remains read-only and
   tolerates historical strings/JSON. Unknown parameters should be handled
   consistently with the repository's DRF conventions and documented
   truthfully in OpenAPI.
5. **Secret and privacy handling.** Session/CSRF/API/identity tokens, invitation
   credentials and links, password/reset material, raw provider payloads, cloud
   credentials, raw headers, cookies, and exception dumps must not enter query
   strings, audit rows, API examples, browser storage, console output,
   screenshots, fixtures, snapshots, logs, or process argv. Prefer numeric
   actor/entity filters in URLs; do not put an email/name free-text search in a
   bookmarkable audit URL. Existing staff-only evidence can include source IP,
   user agent, email, and a verified provider subject in state/context; treat it
   as sensitive data, show it only in an explicit escaped detail, and never copy
   it into logs, telemetry, URLs, or client persistence.
6. **Errors and observability.** Authentication, authorization, validation, and
   not-found failures use `{"error":{"code","message","details?","request_id?"}}`.
   The UI distinguishes denied, invalid-filter, empty, loading, and server-error
   states and may show the request id. It never displays raw exception, SQL,
   provider, or audit-writer errors. Logs carry safe operation/outcome/count and
   request correlation only.
7. **Persistence, retention, and concurrency.** GET is side-effect free and
   queries the append-only database table. Rows may arrive between page reads,
   so deterministic ordering is required and the UI must not imply a frozen
   snapshot. `audit_archive` can remove successfully archived hot rows; PLAT-240
   does not query archive objects or promise history older than the configured
   online retention window.
8. **Config/env and browser-static shape.** Reuse `PLATFORM_SPA_ENABLED` and
   `ADMINISTER_SPA_ENABLED`; no env-manifest, Terraform, Helm, runtime renderer,
   secret reference, or Vite variable changes are needed. Vite output is public
   and cacheable, so it contains only code and fixed labels, never tenant/user
   data or deployment values. Existing CSP, referrer, permissions, CSRF, secure
   cookie, and same-origin policies stay in force; no external asset is needed.
9. **Cloud and OS/runtime exposure.** The API reads Django persistence and has
   no AWS/GCP branch, provider SDK, shell command, worker, task payload, temp
   file, export, or subprocess. Audit data and filters never enter argv or
   environment. This is how AWS/GCP behavior remains identical.
10. **Layer and workflow enforcement.** Backend changes pass Django/pytest,
    Ruff, import-linter, layer/FK checks, OpenAPI drift and compatibility, and
    `adr_guard`; frontend changes pass ESLint, TypeScript, Vitest/axe, Vite, and
    deep-link/route tests. No workflow or guardrail weakening is part of this
    feature.

## Extensibility seams

The durable extension seam remains `shared.audit`: a later invitation, policy,
quota, or user-lifecycle workflow adds a canonical entity/action value only if
the existing vocabulary cannot describe it, then emits one bounded event from
its authoritative service transaction. The reader automatically gains the row;
it does not add per-feature tables, adapters, controllers, or frontend event
classes. Never classify events by parsing prose in `context`.

The read extension seam is one validated filter object applied to one
deterministically ordered `AuditLog` queryset. The next ordinary filter extends
that serializer/query/OpenAPI/query-key path once. Optional actor display
enrichment remains a nullable page projection and cannot replace stable actor
identity. Genuine tenant scoping or online archive retrieval is not an ordinary
filter extension: each needs a separately accepted authoritative scope/source
contract behind `shared`, with cloud adaptation outside the SPA.

The client seam is URL-backed filter state plus a TanStack Query key containing
the complete normalized filter/page object. A refresh or shared link reproduces
the same query without local/session storage. Filters, pagination, and a later
detail drawer/page consume generated types and do not create a client workflow
engine.

## Gotchas and anti-patterns

- Do not implement the real page in the selected-workspace `audit` placeholder
  or imply that changing the workspace switcher changes audit authorization.
- Do not infer organization/workspace scope from entity IDs, current relations,
  JSON state, context strings, actor memberships, or the selected browser UUID.
- Do not create `ActivityLog` rows, an `AdminActivity` model, a search index,
  replicated audit table, browser persistence, or a provider log reader.
- Do not add a second API route, DTO, query parser, event/action enum,
  permission class, exception hierarchy, audit writer, or redaction vocabulary.
- Do not treat `is_staff`, workspace role, organization role, model permission,
  CTF organizer status, token scope, and cloud IAM as interchangeable kinds of
  "admin".
- Do not use current actor/entity names as historical truth, require referenced
  rows to still exist, or add cross-domain FKs/joins to the generic audit model.
- Do not silently accept malformed IDs/dates, invert a time range, advertise
  inert search/ordering, allow arbitrary ORM ordering, or scan JSON/context
  without an explicit bounded/indexed contract.
- Do not remove or narrow published v1 fields, convert historical strings to
  closed response enums, or hand-maintain frontend interfaces/constants that
  can drift from OpenAPI and the shared vocabulary.
- Do not render audit context/state as HTML/Markdown, log it, place it in URLs,
  or copy it into analytics/telemetry. React escaping is required but is not a
  license to expose secrets written by a broken emitter.
- Do not audit every successful read, poll aggressively, auto-retry 4xx, fetch
  every page eagerly, or resolve one actor/entity per row with N+1 queries.

## Non-goals and implementation boundaries

- No audit writer, model/table, migration, vocabulary redesign, mutation API,
  retention-policy change, historical repair, or archive restore/search.
- No organization/workspace-scoped audit authorization and no new tenancy role
  or `WorkspaceOperation` for a deployment-global store.
- No invitation, policy, quota, membership, authentication, or user-lifecycle
  workflow implementation; PLAT-240 displays the events those owner slices
  actually emit and does not synthesize missing history.
- No actor/entity directory, identity-history snapshot, generic entity
  resolver, cross-domain repository, export/download/reporting pipeline,
  websocket/live feed, analytics warehouse, SIEM integration, or alerting.
- No API-token audit scope, successful-read audit policy, per-feature rollout
  flag, provider SDK, cloud log ingestion, infrastructure, worker, CLI, or OS
  integration.
- No change to Django admin at `/admin/`; it remains an independent, read-only
  audit escape hatch alongside the canonical API-backed SPA surface.

## Required proof

The eventual change must preserve the existing writer/admin/archive tests and
add focused evidence at the established boundaries: combined actor/entity/time/
action filtering; invalid and inverted queries returning the shared 400
envelope; deterministic pagination; historical unknown strings; read-only
methods; anonymous/non-staff/token denials (including bearer plus valid
session); denied-read auditing without successful-read writes; OpenAPI/runtime
parity; generated-TypeScript drift; URL filter/query-key behavior; escaped
state/context rendering; loading/empty/denied/error states; keyboard/label/table
semantics and axe coverage; Administer flag-off/deep-link behavior; and proof
that the selected workspace neither scopes nor authorizes the feed.
