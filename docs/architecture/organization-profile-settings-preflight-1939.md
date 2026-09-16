# Organization profile and settings preflight (#1939)

Status: blocked on two architecture inputs

Date: 2026-08-02

Requirements: PLAT-232 (implements), PLAT-241 (constrains)

This note records the minimum repo-wide guardrails for PLAT-232. It is not an
implementation plan and adds no model, migration, endpoint, scope, or SPA
behavior.

## Readiness decision

The slice is not architecture-ready as currently stated.

First, the accepted tenancy decision has no organization administrator.
ADR-046-R8 deliberately makes `owner`, `admin`, and `member` workspace-scoped
and forbids inferring organization authority from one workspace, copying a role
to every workspace, or treating Django staff as organization authority. The
PLAT-231 shell preserves that split: staff admission opens the console, while a
separate live tenancy authorization must admit each child operation. Therefore
neither `is_staff`, `is_superuser`, a Django model permission, nor an
`owner`/`admin` membership in an arbitrary workspace can authorize an
organization update. Implementation must pause until a separately accepted
organization-authority source and its bootstrap/lifecycle semantics exist.
That authority must be exposed through the existing public
`workspaces.services` facade; it must not become a second policy engine in DRF
or TypeScript.

Second, “display/branding and organization-level defaults” is not a field
contract. The current `Organization` has `name` only. `name` is already the
display name and must not be duplicated as `display_name`. `description` is a
clear additive field, but no branding or default field, validation rule,
consumer, inheritance rule, or reset behavior is named. Implementation must
not guess these as a generic JSON settings bag. Before code, the requirement
owner must enumerate each field, its closed type and bound, whether blank means
unset, its default, and the exact product consumer. Each proposed default must
also be checked against ADR-046-R7; deployment configuration, identity, cloud,
catalog, feature flags, audit, CTF, and infrastructure do not become
organization-scoped through this issue.

Once those two inputs are accepted, the bounded design is straightforward:
`workspaces` remains the persistence and policy owner; a public UUID-keyed
resource API delegates a read projection and update command to
`workspaces.services`; and the existing Organization settings route slot uses
the generated API contract and shared SPA infrastructure. No new app,
repository layer, generic settings framework, or admin domain is warranted.

## Fixed boundaries after the blockers are resolved

- The public selector and returned organization identity are the immutable
  `Organization.uuid` only. Integer organization primary keys may remain in
  intra-domain joins and the integer-shaped audit store, but never appear in a
  URL, request body, response DTO, browser route/state, error detail, or log.
- Keep `Organization.name` as the canonical display-name field. Additive
  profile fields belong on the organization-owned persistence contract when
  they are stable first-class facts. Do not add a duplicate DTO/model schema or
  an untyped `settings`, `metadata`, `branding`, or `defaults` JSON column.
- An organization profile update is an organization-scoped operation. Do not
  add it to `WorkspaceOperation` or infer it from `ROLE_OPERATIONS`. The
  accepted organization-authority design must supply an explicit read/update
  operation through `workspaces.services`, returning frozen scalar projections
  rather than ORM objects.
- Console admission remains the PLAT-231 bearer-first staff-session gate and is
  additive to organization authority. The profile API is session-only:
  `IsStaffSession` rejects valid platform tokens, and invalid bearers fail
  closed before session fallback. Do not add or reuse an API-token scope, or put
  an organization UUID/role in a scope string.
- Use an explicit read serializer and an explicit partial-update serializer,
  with an explicit closed-key check because ordinary DRF `Serializer` input
  ignores undeclared keys. The serializer owns HTTP shape, lengths, primitive
  formats, unknown-field rejection, and UUID parsing; the service owns
  authorization, normalization
  that must hold outside HTTP, allowed state transitions, and persistence
  invariants; database constraints own durable bounds. A writable
  `ModelSerializer` calling `save()` from the view would bypass this split.
- Define PATCH semantics as “absent is unchanged” and update only supplied
  fields. This is the extension seam for later approved profile fields and
  avoids a stale form overwriting unrelated additions. A reset-to-default must
  have an explicit wire value and domain meaning; do not overload missing,
  `null`, and empty string.
- Resolve and authorize before returning target-specific data. A well-shaped
  UUID for a missing organization, an organization outside the actor's
  authority, and insufficient organization authority must share one opaque
  outcome so the endpoint does not become a tenant-enumeration oracle.
- The update command is atomic, locks the organization row before mutation,
  rechecks live authority under the accepted authority mutex, writes only
  changed fields, and emits one strict audit event in the same transaction.
  Audit failure rolls back the profile update. No-op PATCH requests do not
  claim a mutation occurred.
- Add the minimum `ORGANIZATION` member to the canonical
  `shared.audit.vocabulary.AuditEntityType`; reuse `AuditAction.UPDATE`, the
  existing `AuditEvent`, request attribution helpers, and strict writer. Audit
  state should identify changed field names and the internal organization ID,
  not copy descriptions, branding URLs/content, organization names, request
  bodies, or other profile text into the durable audit store.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Domain ownership and layering | ADR-001; ADR-046; `workspaces.models.Organization`; public `workspaces.services`; `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `check_model_fks` | Extend the existing domain and facade. No model access from config, management, another domain, or the frontend. |
| Existing tenancy policy | `workspaces.roles`; `workspaces.services._authorization`; locked mutation conventions in `workspaces.services._memberships` | Reuse the facade, opaque denial, frozen projections, atomic locking, and fail-closed operation checks, but do not reinterpret a workspace role as organization authority. |
| Principal and HTTP admission | `config._drf_settings`; bearer-first `ApiTokenAuthentication`; `SessionAuthentication`; `shared.api.principals.active_actor_user`; `IsStaffSession`; exact scope registry | Preserve fail-closed bearer parsing, session CSRF, active-user resolution, console staff admission, and additive live domain authorization. |
| Validation and error shape | Django `<uuid:...>` converter; explicit DRF serializers; `shared.api.errors`; `shared.api.schema.ApiErrorSerializer` | Bound and shape-check once at HTTP, explicitly reject undeclared keys (DRF does not do so automatically), revalidate domain invariants in the service, and return the canonical sanitized request-ID envelope. Do not add a parallel exception hierarchy. |
| Persistence and audit | `Organization.uuid`; Django transactions/row locks; named DB constraints; `shared.audit`; request attribution helpers | Select publicly by UUID, persist internally by PK, serialize concurrent mutation, translate bounded outcomes, and strict-audit in the transaction. |
| Contract publication | `config.api_urls`; `shared.api.schema`; `openapi/v1.json`; `frontend/src/api/schema.d.ts`; `frontend/src/api/types.ts` | Runtime serializers remain authoritative; regenerate the published schema and frontend types rather than hand-copying DTOs. |
| SPA data and forms | `frontend/src/api/client.ts`; `queryClient.ts`; `ApiError`; feature API hooks; existing input/textarea/label/button/card/alert/toast primitives | Use same-origin session/CSRF, request IDs, TanStack Query mutation/invalidation, field errors, accessible states, and existing design primitives. No component-level fetch or role comparison. |
| Console routing and rollout | PLAT-231 organization route slot; `frontend/src/router.tsx`; `features/administer/routes.ts`; `app/nav.ts`; `ADMINISTER_SPA_ENABLED`; `shared.spa_host` | Replace only the existing settings placeholder; add no router, navigation registry, feature flag, bootstrap payload, or cloud-specific path. |
| Logging and documentation | `RequestIDMiddleware`; `shared.log_sanitize`; documentation coverage manifest and existing workspace docs | Log bounded reason/operation codes and post-authorization internal correlation only; extend existing user/technical documentation when the feature ships. |

The CTF `Event.logo_url` and `theme_color` fields are not organization schema
incumbents. CTF is a separate membership and presentation domain under
ADR-046-R7. Copying those fields or their serializers would duplicate policy
without deciding how organization branding is stored, trusted, inherited, and
rendered. In particular, a remote logo URL rendered across organization pages
introduces tracking, mixed-content, CSP, availability, content-type, and
potential SVG/script concerns; data URLs and arbitrary HTML/CSS are also not an
acceptable shortcut. Branding assets need an explicit storage and delivery
contract before they become an approved PLAT-232 field.

## Cross-cutting security and runtime layers

1. **Identity verification and account admission.** `config.oidc`,
   `config.identity_platform`, and `management.services.bind_provider_identity`
   continue to validate issuer, audience/authorized party, subject, and verified
   email before producing the Django user. Organization code consumes that user
   and never parses provider claims or groups. `CTFAccountBoundaryMiddleware`
   remains additive and this endpoint is not a temporary-account bootstrap
   exception.
2. **Browser/session and token authentication.** The SPA uses the one
   same-origin `apiFetch` client, session cookie, CSRF cookie/header, and request
   ID. Bearer parsing stays first and fail-closed. No token, role, organization
   profile, or CSRF value enters local storage. Platform API tokens are rejected;
   programmatic organization-profile administration is a separate future
   surface, not an implicit extension of this SPA slice.
3. **HTTP shape and authorization.** Django/DRF parse the UUID and serializers
   reject unknown, overlong, or malformed fields. Staff/feature/nav checks are
   presentation/admission only. The organization service authorizes the exact
   read or update operation before projection or mutation; the browser's cached
   context and capabilities are never authority.
4. **Persistence and concurrency.** The organization UUID stays immutable and
   unique; internal PK use stays inside the domain/audit adapter. Service-layer
   normalization, database bounds, `transaction.atomic`, row locking, and
   update-only-changed-fields prevent bypass and unrelated-field lost updates.
   No signal, generic model form, direct view save, or cross-layer FK is added.
5. **Errors, logs, and audit.** `shared.api.errors` supplies stable safe codes,
   validation details, and request IDs. Logs use low-cardinality codes and
   `shared.log_sanitize`; they do not contain UUID probes, names, descriptions,
   branding content/URLs, raw serializers, SQL/constraints, cookies, headers,
   tokens, or claims. One strict shared audit event records a real mutation
   without duplicating profile content.
6. **Configuration, secrets, and cloud neutrality.** Organization profile data
   is database-owned product data, not environment or secret configuration.
   PLAT-232 needs no env binding, `shifter.yaml` key, secret-manager value,
   Terraform/Kubernetes/Helm variable, provider branch, or change to
   `config/env-manifest.json`. AWS and GCP execute the same DRF, service,
   persistence, and SPA contracts.
7. **OS/process exposure.** No organization value is placed in process argv,
   shell commands, environment dumps, worker/task payloads, provider labels,
   guest metadata, static bundles, or CI artifacts. The public UUID may occur in
   the browser/API URL but grants no authority by possession.
8. **Repository gates.** The eventual backend slice must pass migration drift,
   Django/workspace/API tests, Ruff/mypy, `lint-imports`, layer/FK checks,
   OpenAPI drift and compatibility, and `adr_guard`. The SPA slice must pass
   generated-type checks, ESLint, TypeScript, Vitest/axe, Vite, and deep-link
   coverage. User and technical docs must reconcile with ADR-022's
   documentation coverage manifest.

## Extensibility seam

The server seam is an actor- and public-organization-UUID-parameterized
`workspaces.services` read/update boundary with a distinct organization
operation and frozen projection. The settings contract is an explicit set of
first-class optional fields with PATCH update masks; adding one approved field
extends that projection, command, serializer, generated contract, and form
without changing identity, routing, policy ownership, or existing fields.

The client seam is the selected public organization UUID. The current PLAT-231
context is membership-shaped and can contain multiple organizations, while the
settings path currently contains no organization UUID. The API path, SPA path
builder, React Router route, TanStack Query key, and service authorization call
must therefore carry the public organization UUID explicitly; they must not
choose the first organization, persist a primary organization, or silently use
the selected workspace's organization. This parameter is required before the
settings form can be correct for a multi-organization principal.

## Gotchas and anti-patterns

- Do not infer organization administration from one/all workspace rows, staff,
  superuser, Django groups/model permissions, CTF organizer status, provider
  groups/claims, API scopes, cloud IAM, or frontend visibility.
- Do not overload `WorkspaceOperation`, duplicate `name` as `display_name`, or
  create a generic settings/metadata/branding/defaults JSON blob.
- Do not move deployment-global cloud, identity, catalog, feature-flag, audit,
  CTF, infrastructure, range-backend, or environment defaults into the
  organization record. Workspace egress/policy is separately governed by
  ADR-046-R10 and is not an organization default by implication.
- Do not use a writable `ModelSerializer`, direct ORM access in a view, a second
  repository/service layer, a new error tree, a second audit event shape, a
  copied frontend DTO/validator, direct `fetch`, or a component role matrix.
- Do not return an integer organization ID incidentally through nested objects,
  links, audit responses, validation details, or generated schemas.
- Do not let GET repair/create tenancy state, let PATCH mutate `uuid`, treat an
  empty payload as reset, audit no-ops, or expose existence through different
  missing-versus-forbidden responses.
- Do not accept remote images, SVG/HTML/CSS, arbitrary URLs, data URLs, or file
  uploads as “branding” until storage, scanning/content-type, CSP, privacy,
  lifecycle, size, and fallback behavior are explicitly accepted.

## Non-goals and implementation boundaries

- No organization authority model is selected by this note; that is the
  unresolved prerequisite, not something PLAT-232 may improvise.
- No organization create/delete/transfer, primary organization, membership or
  administrator lifecycle, invitations, workspace lifecycle, quota, policy,
  range scoping, or audit-view behavior.
- No workspace role redesign, range ownership/access change, CTF schema reuse,
  identity/group synchronization, API-token role, cloud-account/project
  tenancy, or network/isolation change.
- No platform/deployment settings editing, feature flag, new API major,
  frontend framework/store, asset pipeline, provider adapter, worker, or
  provisioner change.
- Only explicitly approved profile/default fields belong in the eventual API
  and UI. “Future-proof” catch-all storage and speculative consumers are out of
  bounds.
