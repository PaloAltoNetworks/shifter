# Organization/workspace admin console preflight (#1938)

Status: pre-implementation guidance

Date: 2026-08-01

Requirements: PLAT-231 (implements), PLAT-241 (constrains)

This note fixes the repo-wide boundaries for the console shell. It is not an
implementation plan and adds no endpoint, route, component, persistence,
invitation, policy, quota, audit view, or cloud behavior.

## Decision and readiness boundary

#1938 composes existing architecture rather than introducing an admin domain:

- ADR-046 and `workspaces.services` remain the only organization/workspace
  persistence and authorization owners.
- ADR-013 and `frontend/src/app/nav.ts` remain the information-architecture and
  navigation source of truth.
- ADR-029 and ADR-040 remain the SPA, browser-auth, DRF, OpenAPI, and generated
  client-contract decisions.
- ADR-045 and `shared.audit` remain the only durable audit capability.
- `/admin/` remains the independent Django admin escape hatch. The SPA neither
  captures nor duplicates deep framework administration.

Staff admission and workspace authority are additive. A browser session must be
staff/superuser to enter the console, and each workspace operation must also be
permitted by the caller's live `workspaces.services` authorization. Neither
gate implies the other: Django staff, groups, and model permissions do not
create workspace authority, while a workspace owner/admin does not admit a
non-staff user to this console.

The current-principal context is a read projection of the caller's existing
workspace memberships. It may group them by organization for presentation, but
it does not create an `OrganizationMembership`, primary organization,
organization-wide role, cloud tenant, or second policy engine. A caller may
belong to workspaces in zero, one, or several organizations.

The shell may register child route slots for later slices, but a route is not a
permission or completed workflow. Organization settings, workspace lifecycle,
invitations, user/range scoping, policy, quota, and audit actions remain
unavailable until their owner issues add explicit service operations and APIs.
The current role matrix contains no organization-settings, quota, policy, or
audit-review authority; ownership of one workspace grants no sibling or
organization-wide authority.

## Principal-context contract

The context read belongs inside the `workspaces` domain below
`/api/v1/workspaces/`. A public `workspaces.services` query returns frozen,
scalar-only projections and the DRF view serializes them. No config,
management, or frontend code imports workspace models or queries memberships.

Keep this read separate from `/api/v1/bootstrap/`. Bootstrap is loaded by every
SPA principal, accepts API tokens, and is admitted through the temporary CTF
account middleware. The tenant-bearing console read is staff-session-only;
putting it in bootstrap would query tenancy on every page and either expose it
outside the console gate or create principal-dependent bootstrap semantics.

Use the canonical bearer-first authentication ordering with `IsStaffSession`.
An invalid bearer fails closed instead of falling through to a valid session,
and a valid platform token (including one owned by staff) is rejected. The
general workspace membership API remains token-capable; do not add a console
token scope.

The minimum safe projection is:

- organization public UUID and display name;
- workspace public UUID, display name, and personal-workspace marker;
- the caller's closed workspace role for display; and
- explicit allowed `WorkspaceOperation` codes derived by the workspace service.

Do not return internal organization/workspace/membership IDs, ORM objects,
member rosters, emails, identity-provider claims, cloud identifiers, or secret
material. Role is display data, not sufficient authorization. TypeScript must
not compare `owner` / `admin` / `member` to reconstruct policy. The service
derives advertised capabilities through the central operation matrix, and each
resource endpoint repeats the authoritative operation check when called.

The response must be multi-organization-safe: use a flat membership-context
result carrying its organization projection or an `organizations[]` grouping.
Do not expose a singular principal/deployment organization, select the first
membership as primary, or enumerate sibling workspaces from an organization
FK. If the cardinality is not explicitly bounded, use canonical DRF page-number
pagination instead of an unbounded custom envelope.

The read is side-effect free. Do not call `resolve_personal_workspace()` from
GET to manufacture a non-empty response or repair malformed state. A staff user
with no membership receives an empty successful projection. Account-lifecycle
bootstrap/repair is a separate decision.

## SPA shell and selection

Reuse the existing `/administer` shell and `administer_spa` rollout. Register a
first-class Organization entry in the central Administer navigation contract,
with route slots for organization settings, workspaces, membership,
invitations, users, range scoping, policy, quota, and audit. PLAT-231 owns only
the layout, routing, context states, switcher, and capability-aware navigation;
later slices own their behavior.

The selected workspace is React Router URL state expressed with its public
UUID. The console layout resolves it against the latest context query before
rendering a child. A missing or stale selection chooses a deterministic visible
fallback or honest empty state; an invalid supplied UUID never silently becomes
the personal workspace. TanStack Query owns the server snapshot. A narrow React
context may expose the validated selection to descendants, but neither it nor
local storage is authority.

Do not persist a `current_workspace_id` on `UserProfile`, add a selection table,
or place internal IDs in routes/cookies/storage. Child API calls send the public
UUID and reauthorize it; cached capabilities only control presentation.

The Django Admin entry remains the existing unflagged, staff-visible,
`external: true` item at `/admin/`, outside the Organization subtree and
`administer_spa` flag. Navigation performs a normal full-page handoff;
`admin.site.urls` is never captured by `/administer/*`.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Tenancy schema and policy | ADR-046; `workspaces.models`; `workspaces.roles`; public `workspaces.services` | Add one frozen read projection behind the facade. No repository layer, model import, role comparison, or copied policy matrix. |
| Browser staff gate | bearer-first `ApiTokenAuthentication`, `SessionAuthentication`, `shared.api.permissions.IsStaffSession`; existing Administer views | Staff-session only; token rejected. Staff admits the console but grants no tenancy operation. |
| HTTP validation and errors | DRF serializers; `config._drf_settings`; `shared.api.errors`; `shared.api.schema.ApiErrorSerializer` | Explicit output shape and shared request-ID envelope. No writable `ModelSerializer`, `JsonResponse`, `csrf_exempt`, or new exception hierarchy. |
| Contract publication | `config.api_urls`; `api_contract`; `openapi/v1.json`; generated `frontend/src/api/schema.d.ts` | Runtime serializers are authoritative. Re-export generated types; never hand-copy DTOs, roles, or operations. |
| SPA server state | `frontend/src/api/client.ts`; `queryClient.ts`; feature API modules | One same-origin session/CSRF client and TanStack Query cache. No direct component fetch, bearer token, Redux store, or parallel retry policy. |
| Routing/navigation | `frontend/src/router.tsx`; `features/administer/routes.ts`; `app/nav.ts`; `RootLayout`; nested-layout precedent in `CtfWorkspaceLayout` | Extend the one router and nav registry. Route/nav visibility is advisory; APIs enforce policy. |
| Rollout/host | `ADMINISTER_SPA_ENABLED`; `_spa_flags_settings`; `_env_manifest`; `config.urls._administer_page`; `shared.spa_host` | Reuse `administer_spa`; add no flag or cloud binding. Disabled deep links 404 and `/admin/` remains independent. |
| UI | Existing app shell, page header, alert, skeleton, select, tabs, table, and dialog components | Reuse accessible loading, empty, denied, stale-selection, and error states; add no second shell/design system. |
| Logging/audit | `RequestIDMiddleware`; `shared.log_sanitize`; `shared.audit`; strict workspace mutation patterns | Do not log/audit routine context reads. Later authority mutations use request-attributed strict audit inside the service transaction. |
| Documentation | documentation-coverage manifest; workspace user/technical docs | Extend existing coverage and vocabulary rather than creating undocumented concepts. |

## Cross-cutting layers the design must pass

1. **Identity and account admission.** Existing OIDC/Identity Platform issuer,
   audience/authorized-party, subject, and verified-email validation binds the
   Django user. The console never parses claims or maps provider groups.
   `CTFAccountBoundaryMiddleware` continues to block temporary participants;
   the new API is not added to their exact bootstrap allowlist.
2. **Browser and session security.** `shared.spa_host` serves only static shell
   markup, redirects anonymous users, and primes CSRF. Session cookies,
   `CsrfViewMiddleware`, `SessionAuthentication`, same-origin fetch, CSP,
   referrer policy, and permissions policy remain in force. No bearer token or
   context payload enters browser persistence.
3. **HTTP authority and shape.** Bearer parsing remains first and fail-closed;
   `IsStaffSession` admits the console read. DRF serializers and canonical
   pagination shape the wire. Feature flags and React gates are not authority.
4. **Tenancy policy.** Query from the actor's memberships and derive operation
   capabilities centrally; never query all organization workspaces and filter
   later. Child endpoints call `authorize_workspace` for the exact operation
   and do not trust a role/capability returned by the browser.
5. **Persistence and races.** Existing FKs, uniqueness, closed-role constraints,
   `transaction.atomic`, and workspace mutexes remain authoritative. This read
   adds no table, signal, migration, selection row, or cross-layer FK and uses a
   bounded `select_related`/prefetch query, not N+1 authorization.
6. **Errors, logs, and audit.** Failures use `shared.api.errors` and request IDs.
   Logs may carry a bounded reason/count and internal correlation, not names,
   UUID probes, emails, role lists, payloads, SQL/provider errors, cookies,
   headers, or tokens. Routine reads are not audit events; later mutations are
   strict-audited through the existing store.
7. **Configuration, secrets, and cloud neutrality.** PLAT-231 adds no setting,
   secret, `shifter.yaml` key, provider claim, Terraform variable, Kubernetes
   value, or AWS/GCP branch. The existing deployment-global non-secret
   `ADMINISTER_SPA_ENABLED` passes `_env_manifest` and both cloud deployments;
   ADR-046-R7 forbids workspace-scoping it.
8. **OS/runtime exposure.** Organization names, roles, context payloads,
   cookies, CSRF values, and internal IDs do not enter argv, environment, task
   payloads, shell commands, provider labels, static bundles, generated reports,
   or CI logs. A public workspace UUID may appear in a browser route but is
   never authority by possession.
9. **Repository gates.** Backend work passes Ruff/mypy/Django tests,
   `lint-imports`, model-FK checks, OpenAPI drift/compatibility, and `adr_guard`.
   Frontend work passes ESLint, TypeScript, Vitest/axe, Vite, SPA-to-`/api/v1`
   enforcement, and deep-link tests. Documentation stays manifest-reconciled.

## Extensibility seams

The server seam is one actor-parameterized, bounded membership-context
projection carrying organization data and operation codes from the central
policy. A later protected action deliberately extends `WorkspaceOperation`, its
one matrix, the generated contract, and its endpoint; it does not add component
role comparisons or a second capability table.

The client seam is the selected public `workspaceUuid` in a nested route plus
an optional required-workspace-operation field in the existing console
navigation/route metadata. A second organization, new workspace, or stale deep
link needs no bootstrap/global-store/provider change. A future genuine
organization authority model requires a separate accepted decision and can
then contribute capabilities without reinterpreting workspace roles.

Cloud/provider adaptation remains outside this feature. Deployment validates
`CLOUD_PROVIDER` once and existing `shared.cloud` protocols/factories or the
configured Django email backend select adapters. DRF and SPA contracts remain
identical on AWS and GCP.

## Gotchas and anti-patterns

- Do not conflate the SPA console, Django admin, tenancy workspace, Terraform
  workspace, cloud account/project, CTF event/team, or range network boundary.
- Do not infer organization authority from one workspace, staff/superuser,
  Django groups/model permissions, user type, CTF authority, provider groups,
  API scopes, or cloud IAM.
- Do not expose only roles and rebuild policy in TypeScript; returned operations
  are advisory and endpoints still reauthorize.
- Do not mutate/repair tenancy in GET, fake a global default workspace, or hide
  an empty membership state.
- Do not extend bootstrap with tenant data, admit tokens to the console read, or
  add it to temporary-participant allowlists.
- Do not create a generic admin CRUD API, writable model serializer, duplicate
  frontend DTO/validator/role matrix, repository, exception tree, audit store,
  router, query client, nav registry, or persistent client store.
- Do not authorize children only at the parent route. Flags, nav, switcher,
  disabled controls, and cached context remain advisory.
- Do not rename/capture `/admin/`, flag its nav entry, iframe it, or duplicate
  rare Django admin operations in the SPA.
- Do not pre-build invitations, policies, quota ledgers, range workflows, audit
  stores, cloud adapters, or provider branches in the shell issue.
- A later invitation must not reuse CTF codes, API tokens, password-reset
  material, or a hand-rolled bearer; it needs purpose-separated expiry,
  one-time/revocation semantics, non-leaking errors, and the configured email
  boundary.

## Non-goals and implementation boundaries

- No organization-wide authority model or primary/current tenant persistence.
- No organization/workspace create, delete, transfer, rename, or settings
  mutation.
- No membership, invitation, user-lifecycle, range-scoping, policy, quota, or
  audit capability implementation; PLAT-232 through PLAT-240 own those slices.
- No continuous membership push/revocation channel; query refetch/invalidation
  plus endpoint reauthorization is the control-plane boundary.
- No change to range ownership/access, CTF membership, API-token scopes,
  identity binding, cloud selection, email credentials, infrastructure,
  workers, provisioners, or Django Admin behavior.
- No new feature flag, frontend framework, API major, schema source, exception
  hierarchy, logging format, or audit backend.
