# SPA Admin Workspace Preflight (#1373)

Status: pre-implementation guidance

Date: 2026-07-14

Issue: GitHub #1373, "SPA Phase 2: Admin workspace (users, cost tracking)"

Requirement: none. The GitHub issue title, body, constraints, and acceptance
criteria are the shipping contract.

This note sets repo-wide architecture guardrails for the Administer workspace.
It is not an implementation plan and does not implement routes, components,
APIs, serializers, services, persistence, flags, tests, or legacy-route
retirement.

## Scope And Readiness Boundary

#1373 must build on the accepted SPA and platform-shell work:

- ADR-013: one shared, role-aware platform IA and navigation contract. The
  canonical product term is **Administer**; **Django admin** means the framework
  surface at `/admin/`.
- ADR-029: React 18, TypeScript, Vite, React Router v7, TanStack Query v5, one
  Django origin, canonical `/api/v1/`, session plus CSRF for browser calls, and
  no browser-held `shf_` API tokens.
- `docs/design/spa-cohesive-ux-1368.md`: Administer covers Users, Cost, and
  Platform Settings and must use the shared page/state/accessibility patterns.
- `docs/architecture/spa-platform-shell-preflight-1369.md`: shared shell,
  navigation metadata, bootstrap, route ownership, and rollout-flag patterns.
- The existing `management`, verified-identity, organizer-authority, CTF
  participant-account, shared audit/error/logging, and Django permission
  boundaries described below.

The repository does not currently provide enough canonical API surface to meet
all of #1373's acceptance criteria. UI implementation must not disguise these
gaps as completed workflows:

| Area | Existing authority | Readiness decision |
| --- | --- | --- |
| User and group administration | Django `auth` models/admin, `management.models.UserProfile`, and narrow services in `management.services` | No `/api/v1/` user-management API exists. A canonical management API with explicit operations, permissions, validation, and strict audit is a prerequisite for SPA-native management. `/admin/` remains the honest interim path. |
| Privilege administration | Deployment-controlled staff bootstrap, organizer-authority services, user-type synchronization, Django model permissions, and CTF account services | There is deliberately no generic "role" owner. Each privilege has a different authority and lifecycle. Generic group or role PATCH is not an acceptable shortcut. |
| Cost reporting | Deployment/IaC budget configuration and connector permissions exist, but no portal cost model, provider service, ingestion path, or `/api/v1/` contract exists | Cost viewing is blocked on a separately owned canonical read API and declared data source. A gap/degraded state is useful but does not satisfy "view cost/reporting works." |
| Platform administration | Django admin and deployment-owned environment/IaC configuration | No general platform-settings mutation API exists. Account settings are not platform configuration. The SPA must not turn environment, Terraform, Kubernetes, cloud, or secret configuration into an unvalidated settings form. |
| Audit review | `risk_register.models.AuditLog` through shared audit policy; `/api/v1/audit/` is Risk Register permission-scoped | The existing endpoint is not a general staff audit feed. Do not weaken its permissions or clone its store. Any broader read surface needs an explicit canonical API authorization contract. |

The SPA may ship the reversible workspace shell, navigation, legacy handoff, and
truthful unavailable/degraded states while those API gaps remain. It may not be
declared acceptance-complete until the user-management and cost workflows have
canonical `/api/v1/` support and pass their authoritative policies.

No new ADR is required if #1373 stays within ADR-001, ADR-013, and ADR-029. An
ADR update is required only if implementation changes an enforceable guardrail:
the frontend stack, auth posture, API boundary, navigation source of truth,
route-retirement policy, audit store/policy, identity authority, import/layer
rules, static-asset policy, CI gates, or deployment/runtime ownership.

## Architecture Decisions And Guardrails

- The SPA Administer workspace owns presentation, route and query state,
  accessible interactions, confirmation UI, and client orchestration. It does
  not own identity proofing, privilege authority, account lifecycle, cost
  collection, cloud access, audit policy, validation, or persistence.
- Use `/administer/` as the SPA route-ownership prefix. Keep `/admin/` mapped
  directly to `admin.site.urls` in every rollout state. Do not iframe, proxy,
  restyle, wrap, or capture Django admin routes and do not describe a link to
  `/admin/` as a SPA-native workflow.
- Gate `/administer/` with a non-secret, per-surface server flag in addition to
  the platform SPA flag. Read flags per request, surface advisory state through
  bootstrap, and preserve a full-page legacy handoff. Flag-off must leave
  `/admin/` and all existing server behavior unchanged.
- All SPA data access uses canonical DRF routes under `/api/v1/`. If the
  separately tracked API consolidation supplies management APIs, the
  `management` app remains the domain owner and exposes public services rather
  than importing another app's models. Do not add component-local JSON views,
  call Django admin/form routes from fetch code, or query cloud providers from
  the browser.
- Browser access to privileged management APIs is session-only unless a
  separate programmatic-admin threat model and narrow token scopes are
  accepted. The existing API-token registry has no management scope; do not
  repurpose a wildcard or another domain's scope and never place a token in the
  SPA.
- Enforce Django model permissions and operation-specific policy at each API;
  `is_staff`, a visible nav item, a bootstrap flag, or an enabled button is not
  sufficient authorization. Expose fine-grained capabilities to the SPA only
  as advisory rendering hints; the endpoint repeats the authoritative check.
- Model user administration as named operations with explicit writable fields,
  preconditions, service ownership, and audit semantics. Do not expose a broad
  `ModelViewSet` or mass-assignment serializer over `User`, `Group`, or
  `UserProfile`.
- Preserve privilege authorities. Staff/superuser state is reconciled by
  verified-identity and deployment bootstrap policy; CTF Organizer state uses
  `config.organizer_authority`; self-service user type cannot grant organizer,
  staff, superuser, or Threat Research; temporary CTF accounts use
  `ctf.services.participant.accounts`. The SPA must not create a synthetic
  generic-role abstraction over these distinct policies.
- Preserve identity binding. Provider subject, issuer, event-account origin,
  organizer provenance, and provider groups are server-derived, bind-once, or
  immutable facts. They are not editable profile fields and should not be
  returned to ordinary list clients merely because they exist on a model.
- Keep account states distinct: `User.is_active`, profile soft deletion,
  anonymization, provider unbinding, privilege revocation, password reset, and
  CTF event-account cleanup are not synonyms. Every destructive action needs
  precise language, impact copy, authoritative service behavior, and a
  deliberate confirmation.
- Use the canonical shared audit store and vocabulary. Privilege and destructive
  mutations require strict, request-attributed audit in the same transaction or
  an existing atomic service boundary; an audit failure must not leave an
  unaudited privilege change. `management.models.ActivityLog` is historical,
  and `management.services.log_activity` is deprecated.
- Cost is a read/reporting concept in this issue, not cloud-control access.
  Actual cost, forecast, configured budget, allocation, and resource usage are
  different facts and must be labeled separately. No repository incumbent
  currently authorizes a live provider call or establishes a portal source of
  truth.
- Platform settings are limited to settings backed by an existing validated
  service/API. Deployment env, Identity Platform/Cognito configuration,
  Terraform, Kubernetes, cloud accounts, bootstrap-admin lists, secrets, and
  provider policies remain deployment-owned and out of browser reach.
- Reuse the shared SPA client, generated OpenAPI types, query client, error
  class, router, shell/nav contract, state mappings, Tailwind v4/shadcn/ui
  primitives, Apple-dark theme, Shifter mark, and favicon. Do not create an
  Admin-specific client, DTO package, exception hierarchy, validation library,
  audit vocabulary, router, store, table system, or visual language.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1373 |
| --- | --- | --- |
| SPA and API client | ADR-029; `docs/architecture/spa-cutover-architecture-1300.md`; `frontend/src/router.tsx`; `frontend/src/api/client.ts`; `frontend/src/api/queryClient.ts`; `frontend/src/api/types.ts` | One router, query client, typed fetch client, generated OpenAPI schema, and `/api/v1/` boundary. |
| Shell, IA, and visual system | ADR-013; `frontend/src/app/nav.ts`; `frontend/src/components/app-shell.tsx`; `frontend/src/app/RootLayout.tsx`; `frontend/src/components/ui/*`; `frontend/src/app/state-map.ts`; #1368 and #1369 docs | Register Administer centrally; reuse the locked theme, primitives, state intent mapping, focus, table, form, dialog, alert, and empty-state patterns. |
| User profile persistence | `management.models.UserProfile`; `management.services.get_user_profile`, identity binding/resolution, and `mark_user_deleted` | Extend public management service seams only when required; do not mutate profile/identity fields directly from views or import management models across app boundaries. Existing narrow services are not a complete management workflow. |
| Django accounts and permissions | `django.contrib.auth` User/Group permissions and Django admin | Reuse model permissions such as view/change rights as operation inputs. Staff admission is not blanket authorization and generic Django-model CRUD is not the product API. |
| Staff/superuser authority | `config.bootstrap_admin` and verified-identity policy | Treat deployment-reconciled staff/superuser fields as read-only in the SPA. Do not create a competing database-managed authority. |
| Organizer and account-type authority | `config.organizer_authority`; `config.user_type_sync`; `shared.auth` | Use canonical predicates, exact role synchronization, provenance, and fail-closed audit. Do not duplicate group strings or infer a role from UI mode. |
| Temporary CTF accounts | `ctf.services.participant.accounts`; immutable `UserProfile.is_ctf_account` and event provenance | Keep event-scoped create/rename/password/anonymize lifecycle in CTF services. Do not treat temporary participant identities as normal provider accounts. |
| API auth and permissions | `config/_drf_settings.py`; `shared.api_tokens.authentication`; `shared.api_tokens.permissions`; module permission classes | Keep session plus CSRF for the browser, fail-closed bearer parsing, explicit permissions, and no implicit management token scope. |
| Validation and contracts | DRF serializers, explicit service preconditions, `/api/v1/schema/`, `frontend/src/api/schema.d.ts` | Backend validation is authoritative; generate frontend types and use client checks only for responsiveness. Use explicit read/write fields and bounded query serializers. |
| Audit and persistence | `shared.audit.policy`; `shared.audit.events`; `shared.audit.vocabulary`; `shared.audit.attribution`; `risk_register.models.AuditLog` | One immutable audit store and vocabulary, request attribution, strict audit for privilege/destructive mutation, no `ActivityLog` revival or frontend audit schema. |
| Errors and observability | `shared/api/errors.py`; `shared.errors`; `frontend/src/api/errors.ts`; `config.middleware.RequestIDMiddleware`; `config/logging.py`; `shared.log_sanitize` | Preserve the safe error envelope, request ids, ECS logs, message classification, and redaction. |
| Rollout and rollback | `shared/spa_host.py`; `config/api_bootstrap.py`; existing per-surface settings flags; `config/urls.py`; `admin.site.urls` | Add a non-secret Administer flag through the existing host/bootstrap/config pattern; keep `/admin/` independent and available. |
| Environment/runtime binding | `config/settings.py`; `config/_env_manifest.py`; `config/env-manifest.json`; `platform/terraform/modules/portal/ec2/user_data.sh`; `scripts/portal-deploy/deploy_portal.sh`; `scripts/gcp/render_runtime_env.py`; `platform/charts/shifter/templates/configmap-runtime.yaml` and values | Bind only the non-secret rollout boolean where needed. Do not move secrets or cost-provider credentials into Vite variables, ConfigMaps, command arguments, or browser-visible bootstrap. |
| Architecture gates | `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `scripts/adr_guard/adr_guard.py`; frontend and Django quality workflows | Preserve composition-root, cross-layer service, generated-schema, frontend, accessibility, and ADR checks. |

There is intentionally no canonical cost-service row to reuse: the repository
contains deployment budget configuration and generated connector permissions,
but neither is a portal reporting contract. Generated infrastructure artifacts
must not become application dependencies.

## Cross-Cutting Layers The Design Must Pass

- Auth surface: an authenticated Django session precedes SPA access. Unsafe
  management calls pass `CsrfViewMiddleware` and DRF `SessionAuthentication`
  with `X-CSRFToken` from the shared client. Login, logout, identity proofing,
  and provider MFA remain server/provider flows.
- API-token parser surface: `ApiTokenAuthentication` stays first and
  fail-closed; an invalid bearer credential never falls through to a session.
  Browser code stores and sends no `shf_` token. Until explicit management
  scopes and policy exist, management endpoints reject token principals.
- Route and participant boundary: `/administer/` is server flag-gated and
  session protected; `/admin/` retains Django's staff admission. CTF
  participant-only policy and event-account boundaries remain in force. Client
  routing, nav visibility, and flags never grant access.
- Authorization/policy surface: Django model permissions, operation-specific
  permissions, `shared.auth` predicates, verified staff bootstrap,
  organizer-authority checks, and CTF account service policy all remain
  authoritative. The design satisfies this layer by deriving advisory
  capability flags from those facts and repeating checks at every read and
  mutation endpoint.
- Identity and privilege shape surface: verified issuer/subject tuples,
  deployment admin lists, provider groups, local organizer grants,
  `UserProfile.user_type`, `is_ctf_account`, and event provenance have distinct
  validators and reconciliation behavior. The design uses named operations and
  read-only fields instead of flattening them into a role DTO.
- Payload/query validation surface: DRF serializers use allowlisted fields,
  typed query parameters, pagination, bounded search/date ranges, and service
  preconditions. Server validation remains authoritative; generated TypeScript
  types prevent schema copies but do not replace runtime validation.
- Secret and privacy surface: passwords, reset material, session/CSRF/API/ID
  tokens, provider subjects and payloads, group claims, audit blobs, cloud
  credentials, private hostnames, cloud account/project identifiers, and raw
  cost line items must not enter static bundles, localStorage/sessionStorage,
  query strings, logs, schema examples, snapshots, screenshots, support copy,
  GitHub artifacts, or process argv. User list responses and browser logs use
  the minimum identity data required for the authorized task.
- Config/env shape surface: the Administer rollout switch is a non-secret
  boolean in Django settings. If a binding is added, account for the literal
  discovery rules in `config/_env_manifest.py`, regenerate/update
  `config/env-manifest.json`, and validate each AWS/GCP runtime binding that
  needs it. Vite build-time variables do not carry deployment state.
- Static asset surface: Vite output is public and cacheable through
  staticfiles/WhiteNoise. It contains no user, deployment, tenant, cost,
  provider, or secret values.
- Error-envelope surface: `/api/v1/` failures use
  `{"error": {"code", "message", "details?", "request_id?"}}`. The UI may
  render safe field errors, permission/validation messages, and request ids; it
  must not expose exception text, SQL/provider/cloud errors, identity details,
  raw audit JSON, or secret-bearing response bodies.
- Logging/observability surface: `X-Request-ID` flows through the shared client
  and `RequestIDMiddleware`; server logs use ECS formatting and sanitizers.
  Record safe operation names, outcomes, actor ids, target ids, and request ids,
  not emails, names, provider identifiers, credentials, group payloads, or cost
  account identifiers.
- Audit/transaction surface: the shared audit policy and immutable AuditLog
  remain the record. Privilege and destructive changes use strict audit with
  request attribution inside the atomic service boundary. UI telemetry and
  ordinary application logs are not audit evidence.
- Persistence surface: Django auth and `UserProfile` remain authoritative for
  current account facts; the audit store remains immutable history. Browser
  query cache is disposable. No shadow user, role, permission, cost, or audit
  table is introduced to make the SPA easier to build.
- Import/layer surface: ADR-001 and `.importlinter` keep `management` isolated
  from feature apps and keep `config` as composition root without direct domain
  model imports. Cross-layer behavior uses `shared` contracts and public
  service facades. Frontend code does not alter this Python boundary.
- OS/runtime exposure surface: the workspace introduces no cloud CLI, shell
  command, worker, temp-file exchange, browser-to-provider credentials, or
  cost-provider call. The non-secret flag may pass through existing runtime
  configuration. Tokens, credentials, identities, and cost data never pass via
  command arguments or emitted build/test artifacts.
- Accessibility surface: list, filter, detail, form, permission, validation,
  error, destructive-confirm, unavailable, and degraded states meet WCAG 2.1
  AA with keyboard access, programmatic labels, semantic tables/forms/dialogs,
  focus management, live status, reduced motion, non-color-only meaning, and
  accessible virtualized/paginated results.

## Extensibility Seams

- Route-ownership seam: Administer is parameterized by SPA prefix, per-surface
  rollout flag, legacy destination, shared nav metadata, and client routes.
  Users, Cost, and Platform Settings can cut over independently without
  capturing `/admin/` or copying the SPA host.
- Capability seam: bootstrap may expose fine-grained advisory capabilities such
  as view users, change an allowed account field, or view cost. Capabilities are
  derived from backend permissions and operation policy. A future privilege
  adds a named policy/service action rather than another generic role string or
  shell branch.
- Account-read seam: a typed, paginated query separates provider-backed users,
  local/development users, and event-scoped CTF accounts and preserves distinct
  lifecycle facts. Future filters extend validated query metadata rather than
  adding parallel list endpoints or frontend-owned classification.
- Account-command seam: each mutation has its own allowlisted request shape,
  permission, validation, service operation, audit event, idempotency/concurrency
  semantics, and cache invalidation. The next safe account action extends this
  command surface rather than enabling generic object PATCH.
- Cost-query seam: the future canonical read contract needs explicit period,
  granularity, scope/provider/environment, currency/unit, source, and
  `as_of`/freshness metadata, with bounded ranges and pagination where needed.
  This keeps a later provider or deployment variation from hardcoding an AWS
  monthly-cost assumption into React. The seam does not authorize or implement
  provider adapters in #1373.
- State seam: loading, initial empty, filtered empty, permission denied,
  validation error, backend error with request id, unavailable API, stale data,
  read-only/degraded mode, and destructive confirmation use shared patterns.
  New server states extend typed mappings rather than a local workflow engine.

## Whole-Repo Scope

#1373 implementation must evaluate these surfaces together:

- Architecture/design: ADR-001, ADR-013, ADR-029,
  `docs/design/spa-cohesive-ux-1368.md`,
  `docs/design/ux-003-information-architecture-sitemap.md`,
  `docs/design/spa-design-system-foundation-1299.md`,
  `docs/architecture/spa-cutover-architecture-1300.md`,
  `docs/architecture/spa-platform-shell-preflight-1369.md`, and this note.
- Frontend: `shifter/shifter_platform/frontend/package.json`, `vite.config.ts`,
  `src/router.tsx`, `src/api/*`, `src/app/*`, `src/components/*`, the existing
  feature folders as patterns, and any Administer feature folder.
- Django composition/config: `config/urls.py`, `config/api_urls.py`,
  `config/api_bootstrap.py`, `config/settings.py`, `config/_env_manifest.py`,
  `config/env-manifest.json`, `config/_drf_settings.py`, `config/middleware.py`,
  `config/logging.py`, `shared/spa_host.py`, and Django `admin.site.urls`.
- Account and identity policy: `management/models.py`, `management/services.py`,
  `management/admin.py`, `shared/auth.py`, `config/bootstrap_admin.py`,
  `config/organizer_authority.py`, `config/user_type_sync.py`, verified-identity
  code, and `ctf/services/participant/accounts.py`.
- Shared contracts and records: `shared/api/errors.py`, `shared/errors.py`,
  `shared/api_tokens/*`, `shared/audit/*`, `shared/log_sanitize.py`,
  `risk_register/models.py`, and the existing Risk Register audit API and
  permissions as a bounded reference, not a general-admin shortcut.
- Legacy compatibility: `/admin/`, `management` Django-admin registrations,
  account/settings templates, and existing identity/provider flows only as
  rollback and behavioral evidence, never SPA data dependencies.
- Runtime/deployment: AWS portal user data and deploy scripts, GCP runtime-env
  rendering, Helm runtime ConfigMap/values, container image build, Django
  staticfiles/WhiteNoise, and any environment documentation affected by the
  non-secret flag. Cost credentials and provider access are not added here.
- Enforcement/workflows if touched: `.github/workflows/**`, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/adr_guard.py`, OpenAPI generation, frontend
  ESLint/typecheck/Vitest/axe/Playwright/build, Django tests, ruff, and
  import-linter.

## Gotchas And Anti-Patterns

- Do not redesign the Apple-dark Tailwind v4/shadcn/ui theme, brand, logo,
  favicon, typography, or color language.
- Do not capture `/admin/` with an SPA catch-all, iframe Django admin, call
  Django admin/form URLs from SPA data code, or remove legacy admin behavior.
- Do not claim an unavailable/degraded placeholder, iframe, or legacy link
  satisfies a working SPA-native user or cost workflow.
- Do not create ad hoc endpoints, a parallel API version, GraphQL layer,
  component fetch wrappers, hand-copied DTOs, local validation schemas, error
  classes, exception hierarchies, audit stores, or role vocabularies.
- Do not equate operator mode, staff, superuser, Django model permissions, CTF
  Organizer, CTF Participant, Threat Research, `UserProfile.user_type`, provider
  groups, or API-token scopes.
- Do not generically edit groups or `is_staff`/`is_superuser`; do not bypass
  verified deployment authority, organizer provenance, role-sync audit, or
  event-account restrictions.
- Do not conflate disabling login, soft deletion, anonymization, privilege
  removal, provider unbinding, password reset, and permanent deletion. Do not
  offer an operation for which the repository lacks a complete service
  contract.
- Do not expose provider subject/issuer, group claims, bootstrap-admin lists,
  passwords/reset values, raw audit details, cloud credentials, cloud
  account/project ids, or cost line items merely because an administrator is
  viewing the page.
- Do not equate actual spend, forecast, budget, allocation, usage, or list
  price. Do not scrape Terraform, generated CloudFormation, deployment output,
  provider CLIs, logs, or billing consoles as a runtime data source.
- Do not turn Mission Control account settings into platform settings or add a
  generic key/value settings API over environment/IaC-owned configuration.
- Do not allow unbounded user search, bulk export, cost date ranges, or raw
  provider reports; enforce pagination, minimum data, bounded filters, safe
  ordering, and authorization server-side.
- Do not auto-retry unsafe, privilege-changing, or destructive operations.
  Handle concurrency and stale state explicitly and require a fresh deliberate
  confirmation after failure.
- Do not render user content, audit details, provider errors, or cost metadata
  as HTML/Markdown without an accepted sanitizer policy.
- Do not weaken ADR guard, import-linter, Django/DRF checks, OpenAPI generation,
  SPA lint/typecheck/unit/axe/e2e/build checks, or legacy rollback tests.

## Non-Goals And Implementation Boundaries

- No implementation of SPA pages, routes, components, APIs, serializers,
  services, persistence, migrations, flags, tests, or route cutover in this
  preflight.
- No retirement, replacement, restyling, wrapping, or access-control weakening
  of Django admin at `/admin/`.
- No complete user-management claim until canonical `/api/v1/` operations
  exist for the accepted workflows with explicit permissions, validation,
  identity boundaries, strict audit, and generated types.
- No cost-reporting claim until a separately owned canonical source and
  `/api/v1/` read contract exist. No cost ingestion, allocation engine,
  provider adapter, cloud permission expansion, budget enforcement, invoicing,
  or billing workflow is introduced here.
- No browser editing of deployment env, Terraform, Kubernetes, Identity
  Platform/Cognito, provider policies, bootstrap-admin lists, secrets, or cloud
  accounts.
- No replacement of Django sessions, CSRF, OIDC/Identity Platform/Cognito,
  dev-login policy, CTF magic links, API-token authentication, Django model
  permissions, organizer authority, verified identity, audit persistence, or
  provider logout/MFA behavior.
- No new repository/domain layer, generic identity platform, role engine,
  workflow engine, validation framework, exception hierarchy, audit system,
  reporting warehouse, second server/origin, SSR framework, or CORS posture.
