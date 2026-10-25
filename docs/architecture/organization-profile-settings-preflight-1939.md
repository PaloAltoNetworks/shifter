# Organization profile and settings preflight (#1939)

Status: architecture-ready, with ADR-066 activation boundaries

Date: 2026-09-20

Requirements: PLAT-232 (implements), PLAT-241 (constrains)

This note records the repo-wide guardrails for PLAT-232 after ADR-066. It is not
an implementation plan and adds no model, migration, endpoint, scope, or SPA
behavior.

## Decisions and boundaries

- `workspaces` remains the persistence and authorization owner. Public callers
  use `workspaces.services`; API views and the SPA do not query tenancy models or
  compare role strings.
- An organization settings resource exists only beneath a `team` or
  `enterprise` `Account`. An `individual` account has no organization or
  workspace. Cross-row account-kind validity is proved by
  `workspaces.services`, since a database check constraint cannot inspect the
  referenced account row.
- Creating the default organization and workspace grants no membership or
  role. A team or enterprise organization may therefore have zero
  administrators until a separately authorized operation creates an explicit
  organization-admin membership. Settings discovery then returns no row to an
  ordinary caller; creation does not infer an administrator from creator,
  account membership, or default status.
- ADR-048 remains the organization profile authority: an explicit persisted
  organization `admin` role, plus the separately audited Django superuser
  override. ADR-066 supersedes ADR-048's former personal-organization bootstrap
  rule. Workspace roles, account association, staff status, Django permissions,
  provider claims/groups, token scopes, cloud IAM, and frontend capabilities do
  not grant organization authority.
- The immutable `Organization.uuid` is the only public selector and returned
  organization identity. Integer keys remain internal join and audit-adapter
  details and never enter URLs, bodies, response DTOs, browser state, generated
  client contracts, validation detail, or application logs.
- `name`, `description`, `support_email`, and `support_url` are the closed
  profile contract. `name` remains the display name. There is no parallel
  `display_name`, generic settings/defaults/branding JSON, or inheritance of
  deployment configuration.
- Reads return frozen scalar projections. PATCH means absent is unchanged and
  empty string clears an optional field. Real updates lock the organization,
  recheck authority under the same organization mutex, write only changed
  fields, and strict-audit in the transaction. Any future admin grant/revoke
  operation must use that mutex too, or update authorization can race revocation.
- ADR-066 permits source schema before the S8 hard cut but forbids mixed runtime
  authority. Before S8, legacy personal rows remain on the existing compatibility
  path. At activation, the organization service admits only proven team or
  enterprise ancestry and principal-based membership; it must not add a partial
  account-kind filter while another runtime path still treats legacy personal
  organizations as live authority.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Domain and account hierarchy | ADR-001, ADR-048, ADR-066; `workspaces.models.Organization`; `workspaces.services._account`, `_organization`; `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `check_model_fks` | Extend the existing domain and facade. Prove Account -> Organization ancestry there; add no repository or admin domain. |
| Principal and role authority | `shared.identity_scope.PrincipalRef`; `management.principals.principal_for_user` behind the ADR-066-required public `management.services` facade; `workspaces.models.OrganizationMembership`; `workspaces.roles.OrganizationRole` | At S8, resolve the authenticated human to the stable principal at the composition boundary and authorize the membership's scalar principal identity. Do not import management models into workspaces or retain user ID as a second authority. |
| HTTP admission | `config._drf_settings`; bearer-first `ApiTokenAuthentication`; `SessionAuthentication`; `shared.api.principals.active_actor_user`; `IsAuthenticatedSession` | Keep the profile API active-session-only, CSRF-protected, and token-denied. `IsStaffSession` is not the profile authority. |
| Validation and errors | Django UUID routing; explicit DRF serializers; service invariant validation; `shared.api.errors`; `ApiErrorSerializer` | Reject unknown keys and malformed values at HTTP, recheck domain invariants in the service, and emit the canonical sanitized request-ID envelope. Map service outcomes once; add no exception tree. |
| Persistence and audit | immutable unique UUID; named database constraints; `transaction.atomic`; `select_for_update`; `shared.audit`; request attribution helpers | Keep public UUID and internal PK roles distinct, serialize mutation, and roll back a mutation when strict audit fails. Audit changed field names, internal ID, and override flag, never field values. |
| Contract publication | `config.api_urls`; `shared.api.schema`; `openapi/v1.json`; generated `frontend/src/api/schema.d.ts` and `types.ts` | Treat runtime serializers as authoritative and regenerate contracts instead of copying DTOs. |
| SPA data and navigation | `apiFetch`; TanStack Query hooks/keys; `ApiError`; `BootstrapPermissionsSerializer`; `app/nav.ts` permission policies; `RouteGate`; existing form/alert primitives | Reuse the advisory capability and navigation seam. Components submit UUID-keyed PATCH masks and never authorize by role. |
| Paging and accessibility | `frontend/src/api/principalContext.ts` complete-page traversal pattern; shared controls; Vitest/Testing Library/axe | Do not silently expose only the first 50 administrable organizations. Preserve labeled fields, error association, focusable denial states, and keyboard navigation. |
| Observability and docs | `RequestIDMiddleware`; `shared.log_sanitize`; documentation coverage inventory and workspace docs | Keep logs bounded and sanitized; update generated/reference docs with the activated contract. |

## Security and runtime layers

1. **Provider and credential proof.** Existing OIDC/Identity Platform validation
   proves issuer, audience or authorized party, subject, verified email, and
   provider-specific session requirements before a Django user exists. Profile
   code consumes the active user/principal and never parses claims or groups.
   `CTFAccountBoundaryMiddleware` remains additive and the profile API is not a
   temporary-account exception.
2. **Browser authentication.** The SPA uses same-origin `apiFetch`, the session
   cookie, CSRF cookie/header, and request ID. Bearer parsing stays first and
   fail-closed; a valid platform token is still refused. No token, CSRF value,
   role, or profile content enters local storage.
3. **Principal and customer policy.** At ADR-066 activation, the existing
   principal-resolution facade produces `PrincipalRef`; `workspaces.services`
   proves team/enterprise ancestry and the exact persisted org-admin grant.
   Missing, cross-account, legacy-unmapped, wrong-kind, and unauthorized targets
   fail closed. Account membership and default status convey no authority.
4. **HTTP shape and enumeration resistance.** UUID routing and serializers bound
   request shape, formats, lengths, and keys. A well-shaped missing UUID and a
   UUID outside the actor's authority return the same opaque 403. Router-level
   malformed paths disclose no target data. Exception strings, SQL constraints,
   integer IDs, and submitted profile values stay out of the response envelope.
5. **Persistence and concurrency.** The service validates outside HTTP, locks
   the organization row, rechecks live authority, writes the PATCH mask, and
   relies on named constraints for durable shape. The mask prevents unrelated
   fields from being reverted, but concurrent edits to the same field are still
   last-write-wins; do not claim optimistic conflict detection. If the product
   later requires it, `updated_at` is the existing version/precondition seam.
6. **Audit and logs.** `shared.audit` is the only durable event path. One strict
   event accompanies a real mutation; a no-op emits none. Logs use request IDs,
   bounded codes, and sanitized internal correlation after authorization. They
   exclude UUID probes, names, descriptions, support values, bodies, headers,
   cookies, tokens, and claims.
7. **SPA visibility and route admission.** The current organization settings API
   accepts a non-staff active org administrator, but the current parent
   `/administer` route, nav entry, and workspace console context are staff and
   workspace-membership gated. The settings surface must use a distinct
   `can_administer_organizations` advisory bootstrap/nav policy derived through
   `workspaces.services`, and it must not require workspace context. The API
   remains authoritative. Individuals and users with no admin grant receive no
   settings navigation; stale direct links still end at the API denial.
8. **Configuration, secrets, cloud, and OS exposure.** Profile data is database
   product data. PLAT-232 adds no env binding, env-manifest shape, secret,
   Terraform/Kubernetes/Helm input, provider branch, workload identity, or cloud
   label. No organization value belongs in process argv, shell commands,
   environment dumps, task payloads, guest metadata, static bundles, or CI
   artifacts. A UUID in a browser/API URL is a selector, never a bearer grant.

## Extensibility seam

The server seam is an actor/principal plus public organization UUID passed to
the existing `workspaces.services` read/update boundary. The account-kind check,
explicit profile-field set, and PATCH mask let a later approved field extend the
projection without changing identity, policy ownership, or routing. The
organization UUID must parameterize the API path, route, query key, mutation,
and audit target; never select the first workspace's organization.

The client seam is the existing advisory bootstrap capability plus the
authority-owned paginated organization list. Add a semantically distinct
organization-admin capability rather than reusing `staff`, `adapter_admin`, or
`model_source_admin`. It controls discovery only and cannot become cached
authority. The list client must traverse or present every page, following the
existing principal-context pagination convention.

## Gotchas and anti-patterns

- Do not infer organization administration from account membership, account
  kind, default status, creator/contact identity, workspace roles, staff,
  provider groups, API scopes, cloud roles, or route visibility.
- Do not seed an admin or workspace owner while creating default hierarchy, and
  do not impose a last-admin invariant on an organization that legitimately
  begins with zero admins. Grant lifecycle is a separate authorized operation.
- Do not leave organization settings under the inherited staff-only route gate
  or the workspace-context layout; both are narrower than the domain authority.
- Do not reuse an integration-specific bootstrap flag for settings authority,
  expose only page one, choose the first organization, or store a “primary”
  organization in browser state.
- Do not duplicate `name`, add a JSON settings bag, accept remote branding
  assets/HTML/CSS, move deployment-global defaults into the organization, or
  reuse CTF presentation fields.
- Do not use a writable `ModelSerializer`, direct view ORM writes, model signals,
  a second repository/service layer, a copied frontend DTO, direct component
  `fetch`, or a frontend role matrix.
- Do not emit integer organization IDs through nested objects, links, errors,
  logs, generated schemas, or audit read APIs. Do not reveal target existence by
  distinguishing missing from forbidden.
- Do not let GET create/repair hierarchy or membership, PATCH mutate identity or
  ancestry, missing fields mean reset, or no-op writes claim an audit event.
- Do not switch only this endpoint to principal/account authority before the S8
  cut while sibling runtime paths still use the legacy personal hierarchy.

## Non-goals

- No account, organization, workspace, membership, or admin grant/revoke
  lifecycle; no create, delete, transfer, invitation, quota, policy, range, or
  audit-reader behavior.
- No API-token scope, authentication protocol, provider claim mapping, OpenFGA
  evaluator, policy cache, cloud tenancy, network/isolation, secret, or
  infrastructure change.
- No generic settings framework, branding asset pipeline, organization-level
  deployment configuration, feature flag, new API major, frontend store/router,
  worker, task, adapter, or provisioner behavior.
- No S8 production cutover or partial legacy migration. PLAT-232 consumes the
  account/principal contracts when the repository-wide authority cut activates.
