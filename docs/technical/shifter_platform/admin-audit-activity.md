# Administrator audit and activity history

The administrator audit and activity history (issue #1947, PLAT-240) is a
read-only surface over the existing durable audit record. It adds no new store,
writer, or event vocabulary. It hardens the existing read API and adds a
staff-facing SPA page. The binding boundaries are recorded in
[`administrative-audit-activity-preflight-1947.md`](../../architecture/administrative-audit-activity-preflight-1947.md)
and constrained by PLAT-241 (cloud-agnostic, proven components).

## Read API

`GET /api/v1/audit/` lists and retrieves rows from the immutable
`shared.models.AuditLog` store. It is the single canonical read API over the
audit record. No parallel audit endpoint, table, or serializer is introduced.

- **Domain.** The view lives in the shared platform layer
  (`shared/api/audit.py:AuditLogViewSet`) and reads `AuditLog` directly. The
  shared layer keeps owning the cross-cutting audit read and does not import a
  product-domain model to enrich rows.
- **Authorization.** Staff-session only, through the shared `IsStaffSession`
  authority rule. The bearer-first authentication chain
  (`ApiTokenAuthentication` then `SessionAuthentication`) rejects an invalid
  token before the session fallback, and a valid platform token authenticates as
  a token principal that the session-only rule then denies. A denied read is
  itself recorded as an `ACCESS_DENIED` audit row. A successful read records
  nothing, so viewing the feed never grows the feed.
- **Filters.** `AuditLogQuerySerializer` validates the query before it reaches
  the queryset: `entity_type`, `entity_id`, `action`, `actor_type`, `actor_id`,
  `request_id`, `from_date`, and `to_date`. The identifiers parse as
  non-negative integers, including the historical sentinel `0`. The time bounds
  parse as timezone-aware datetimes, and a start later than the end is rejected.
  Invalid input returns the shared 400 error envelope rather than being ignored
  or turning into a server error. `action` maps to the event-type dimension and
  the entity and actor dimensions to their type and id pairs, so no overlapping
  event-type taxonomy is introduced.
- **Vocabulary.** The exact-match string filters and the response fields stay
  bounded strings rather than closed enums, because the audit vocabulary is
  append-only and historical rows can carry retired values that must stay
  readable and filterable. The active `AuditAction`, `AuditEntityType`, and
  `AuditActorType` values remain the only vocabulary for new emitters.
- **Ordering and pagination.** Results use the canonical page-number pagination
  and deterministic `-timestamp, -id` ordering, so pages stay stable when rows
  share a timestamp. The endpoint opts out of the global search and ordering
  backends, which defined no truthful fields here, so the published contract no
  longer advertises inert `search` and `ordering` parameters.
- **Contract.** The runtime serializers are authoritative. The generated
  OpenAPI (`openapi/v1.json`) and TypeScript types
  (`frontend/src/api/schema.d.ts`) are regenerated with `npm run gen:api` and
  stay within the ADR-040 compatibility gate: no published `AuditLog` response
  field is removed, narrowed, or retyped.

## SPA surface

The page reuses the existing `/administer` area and the `administer_spa`
rollout. It is a deployment-level surface, not a workspace-scoped one, because
the audit store carries no per-row workspace scope (ADR-046-R7).

- **Routing.** A top-level `audit` route under the `administer` route group
  (`frontend/src/router.tsx`), with the path builder in
  `frontend/src/features/administer/routes.ts`. The page is
  `features/administer/AuditPage.tsx`.
- **Navigation.** An **Audit** entry in the central navigation contract
  (`frontend/src/app/nav.ts`), staff-gated and `administer_spa`-gated. The
  workspace-scoped console (PLAT-231) intentionally has no audit slot, so the
  navigation never implies that the workspace switcher scopes or authorizes the
  feed.
- **Data access.** The `useAuditEvents` hook (`frontend/src/api/audit.ts`) calls
  the endpoint through the shared `apiFetch` client with TanStack Query and the
  generated types. The normalized filter and page object is the query key, and
  filter state lives in the page address, so a refresh or shared link reproduces
  the same query without local storage.
- **Evidence handling.** The row detail disclosure renders `previous_state`,
  `new_state`, `context`, source address, and user agent as escaped data only,
  and only when the row is expanded. It never renders them as HTML, treats them
  as current entity state, or copies them into logs, URLs, or telemetry.

## Cloud agnosticism

The surface reads Django persistence and adds no provider branch, SDK,
subprocess, environment binding, or infrastructure. AWS and GCP deployments
behave identically.
