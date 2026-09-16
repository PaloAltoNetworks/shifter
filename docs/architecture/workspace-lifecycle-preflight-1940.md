# Workspace lifecycle preflight (#1940)

Status: pre-implementation guidance

Date: 2026-08-02

Requirements: PLAT-233 (implements), PLAT-241 (constrains)

This note fixes the boundaries for workspace create, list/search, rename,
archive/restore, and ownership transfer. It adds no application behavior.

## Decision

Extend the existing `workspaces` domain, its public `workspaces.services`
facade, and the existing console/API contracts. Do not create a workspace
repository, generic CRUD/admin API, a second role policy, or a tenant-specific
cloud path.

Organization authority and workspace authority are deliberately different:

- Creating or listing workspaces for an organization requires that
  organization's ADR-048 persisted `OrganizationMembership` `admin` authority
  (or the service-owned superuser override). The requested organization is its
  public UUID; it is never inferred from a first context item, staff status, a
  workspace role, or a cloud deployment.
- Reading or mutating an existing workspace requires a new explicit
  `WorkspaceOperation` checked by `workspaces.services` for that exact public
  workspace UUID. The operation-to-role mapping belongs only in
  `workspaces.roles`; the SPA receives generated data and never compares role
  strings.
- A new ordinary workspace is created with its creator as an owner in the same
  transaction. Its name remains unique within its organization. Personal
  compatibility workspaces are never created, renamed, archived, restored, or
  ownership-transferred through this surface.

The lifecycle service is the transaction boundary. Each mutation locks the
workspace row, rechecks the live authority while locked, performs the state
change, and records one request-attributed `shared.audit` event with
`strict=True` in that same transaction. An audit failure rolls the mutation
back. Transfer is one atomic service command, not a client sequence of role
changes: it must retain an owner throughout and may only operate on an existing
active membership. Its response is a frozen scalar projection, never an ORM
object.

## Archive boundary

Archive is a reversible workspace lifecycle marker (a nullable archive timestamp
is preferable to deletion), not a range lifecycle operation. It MUST NOT
delete, rehome, mutate, or cascade to CMS/Engine range bindings, provider
resources, credentials, CTF state, or audit history. Restore changes only that
marker.

PLAT-233 does not itself authorize a new global meaning of an archived workspace
for existing range access, launch, membership APIs, cleanup, or provisioning.
Those systems retain their current authorization and cleanup behavior until a
separate accepted policy extends their canonical service seams. The lifecycle
list/search contract must instead make archive visibility explicit (default
active-only plus an intentional archived-state filter); a restore route must be
reachable without relying on a hidden row. Do not smuggle an archive check into
`authorize_workspace` and accidentally strand existing range cleanup or change
unrelated APIs.

## Canonical seams and contracts

| Concern | Required incumbent | Boundary |
| --- | --- | --- |
| Authority and persistence | `workspaces.services`, `workspaces.models`, `workspaces.roles`; ADR-046/048 | Facade returns frozen scalar projections; no model import or cross-layer FK outside `workspaces`. |
| Organization discovery | ADR-048 `OrganizationMembership`; `list_administrable_organizations` pattern | Never derive organization reachability from principal context or workspace membership. |
| Input/output shape | Explicit DRF serializers; `shared.api.errors`; `shared.api.schema.ApiErrorSerializer` | Serializer checks HTTP shape; service validates domain invariants; use the shared request-ID envelope. |
| Browser/API security | bearer-first `ApiTokenAuthentication`, `SessionAuthentication`, `IsStaffSession`; `shared.api.principals` | Console lifecycle endpoints stay staff-session-only, CSRF-protected, and reauthorize at the resource service. |
| Audit and logs | `shared.audit`, request attribution helpers, `shared.log_sanitize` | Audit IDs/field names and bounded state only; never names, UUID probes, emails, request bodies, headers, cookies, tokens, or database errors. |
| SPA data | `frontend/src/api/client.ts`, `queryClient.ts`, generated `schema.d.ts`, TanStack Query feature modules | One typed client/query-key family; mutations do not auto-retry; invalidate or seed every affected list/detail/context cache. |
| Routes and navigation | `features/administer/routes.ts`, organization workspace layout/surface manifest, `app/nav.ts` | Public UUID URL state only; navigation/capabilities are presentation hints, never authority. |
| Published contract | `config.api_urls`, `openapi/v1.json`, `npm run gen:api` | Runtime serializers are authoritative; regenerate, do not hand-copy TypeScript DTOs. |

## Security and whole-repository gates

1. **Identity/session gate:** existing OIDC/Identity Platform validation binds
   the Django user. `ApiTokenAuthentication` remains first and fails closed;
   `IsStaffSession` rejects valid tokens as well as non-staff sessions. Do not
   parse claims, accept bearer tokens, or add a temporary-participant allowlist.
2. **Request shape and CSRF:** DRF serializers reject unknown/wrongly shaped
   fields; service validation repeats domain rules for non-HTTP callers. The
   existing same-origin SPA client supplies CSRF and request IDs for unsafe
   requests. No `csrf_exempt`, `JsonResponse`, writable `ModelSerializer`, or
   direct component `fetch`.
3. **Authorization/enumeration:** malformed, absent, unauthorized, and stale
   public workspace UUIDs use the existing opaque tenant-denial behavior.
   Staff, navigation visibility, cached capabilities, organization access, and
   a UUID in a URL do not grant workspace authority. An organization UUID is
   separately authorized for create/list.
4. **Persistence/concurrency:** database uniqueness remains the final name
   invariant; translate `IntegrityError` to a safe classified outcome. Lock and
   recheck all lifecycle mutations, including transfer and archive/restore;
   never implement check-then-save or rely on a UI-disabled button.
5. **Error/audit/log envelope:** map bounded service outcomes through the
   existing workspace API mapper and `api_error_response`; do not expose SQL,
   transaction, provider, range, membership-roster, or target-existence detail.
   Strict audit is transactional and contains only stable internal entity IDs,
   action, bounded state/field names, and trusted request attribution.
6. **Configuration/provider/runtime:** this slice adds no secret, environment
   binding, feature flag, `shifter.yaml` key, Terraform/Kubernetes value, cloud
   claim, AWS/GCP conditional, shell command, worker payload, provider label,
   or process argv value. UUIDs are public identifiers, not credentials; no
   tenant data may enter environment, argv, static bundles, CI output, or logs.
7. **Repository contracts:** preserve ADR-001 import boundaries and ADR-046-R6/
   R7/R8/R11/R12 plus ADR-048. Regenerate OpenAPI and generated types, exercise
   DRF/API error and authorization cases, transactional race/invariant cases,
   and SPA loading/empty/denied/stale/deep-link/error states. Run the applicable
   backend/frontend checks and `adr_guard` required by `AGENTS.md`.

## Extensibility seam

The one workspace lifecycle facade owns a closed workspace projection and an
explicit archive-state filter parameter for list/search. A later lifecycle
operation extends `WorkspaceOperation`, its single role matrix, the service,
the serializer/OpenAPI contract, and the feature API module together. A future
archive effect on range admission/access belongs at the established CMS
pre-reservation or range-authorization seam, with its own policy decision; it
is not a model signal, UI condition, or cloud adapter branch.

## Anti-patterns and non-goals

- Do not conflate an organization/workspace with a cloud account/project,
  Terraform workspace, deployment, CTF team/event, Django group/admin, or a
  range network boundary.
- Do not derive create/list authority from staff, a workspace owner/admin role,
  context data, API-token scope, provider group, or cloud IAM. Do not extend
  `WorkspaceOperation` to encode organization authority.
- Do not delete a workspace, mutate `personal_for_user`, add a global default,
  add `owner_user`, duplicate memberships, create an archive table/workflow, or
  use signals/model `save()` as lifecycle authority.
- Do not hand-roll a DTO, role matrix, validation layer, exception hierarchy,
  audit store, logging format, query client, router, or provider adapter.
- This slice does not create or administer organizations, organization admins,
  invitations, users, memberships, quotas, policy/egress, CTF authority,
  range ownership/access/cleanup, deployment settings, email, infrastructure,
  workers, or Django admin behavior. Deep/rare administration stays at
  `/admin/`.
