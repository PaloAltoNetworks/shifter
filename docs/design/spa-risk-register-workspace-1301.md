# SPA Risk Register Workspace Design - Issue 1301

Status: design artifact and pre-implementation guidance

Date: 2026-07-05

Issue: GitHub #1301, "SPA phase 1 design: Risk Register workspace"

Milestone: SPA Cutover

Requirement: none. This is a requirement-free run; the GitHub issue is the
shipping contract.

This note defines the phase-1 Risk Register SPA workspace boundary. It is a
design contract, not an implementation plan. The workspace must conform to
ADR-029 and the SPA design-system foundation:

- `docs/architecture/spa-cutover-architecture-1300.md`
- `docs/design/spa-design-system-foundation-1299.md`
- `docs/design/design-system/`

No new ADR is required for this issue unless implementation changes the
frontend stack, route-retirement policy, auth posture, API boundary, static
asset policy, CI guardrails, or import/layer rules.

## Scope Boundary

The Risk Register SPA is a module-level workspace over the existing canonical
Risk Register domain:

- `risk_register.models.Risk`, `Comment`, and `AuditLog` remain authoritative.
- `risk_register.api.views.RiskViewSet`, `CommentViewSet`, and
  `AuditLogViewSet` remain the canonical HTTP surface under `/api/v1/`.
- `risk_register.api.serializers` remain the HTTP validation and response
  shape owners.
- `risk_register.access.principal_has_risk_register_access`,
  `risk_register.api.permissions`, and `shared.api_tokens` remain the
  authorization boundary.
- `risk_register.services` remains the canonical audit facade for new audit
  writes.
- `shared.db.SoftDeleteManager` / `SoftDeleteQuerySet` remain the soft-delete
  pattern. `Risk.objects` and `Comment.objects` are active-only; `all_objects`
  is the explicit full-table escape hatch.

The SPA may improve presentation, routing, and client-side ergonomics. It must
not move risk validation, audit behavior, soft-delete semantics, permission
checks, or workflow transitions into frontend-only logic.

## Architecture Decisions And Guardrails

- Build the workspace as part of the ADR-029 SPA: React 18, TypeScript, Vite,
  Django staticfiles/WhiteNoise, single origin, session cookie plus CSRF header,
  and no browser-held `shf_` API tokens.
- Consume only `/api/v1/` endpoints. Do not call existing Django HTML action
  routes from SPA code except for compatibility redirects outside the SPA
  client.
- Generate Risk Register client types from `/api/v1/schema/`. Do not hand-copy
  Risk, Comment, AuditLog, severity, status, or STRIDE schemas into feature
  code.
- Keep UI state separate from domain state. Design-system badges express
  intents such as danger, warning, info, neutral, and success; `Risk.status`,
  `Risk.severity`, soft-delete state, and audit actions remain backend domain
  values.
- Hidden or disabled controls are only UX affordances. Every mutation still
  relies on DRF authentication, risk-register group access, staff/session or
  token scope checks, serializer validation, and audit persistence.
- Treat descriptions, mitigation text, attack vectors, affected assets, and
  comments as untrusted user content. Render them as text with preserved
  line-breaks; do not render Markdown/HTML or inject them into class names,
  CSS, HTML IDs, inline scripts, logs, examples, or screenshots.
- Preserve existing Django Risk Register routes until a module-specific
  implementation issue explicitly retires or redirects them.

## Runtime Library Decisions (Platform Defaults)

ADR-029 fixed the framework, language, and bundler (React 18, TypeScript,
Vite) and deferred two client libraries to this first module so they are
proven on a real surface before becoming platform defaults
(`spa-cutover-architecture-1300.md`, "Frontend stack choice"; issue #1301
discussion). This design makes both choices. They are the default for the
later SPA modules (Mission Control, CTF, Scenario Editor, Docs), so
"Formalization" below recommends promoting them to an ADR-029 addendum.

### Client router: React Router v7 (library mode)

Decision: React Router v7 in its library / data-router mode
(`createBrowserRouter`), not the framework/SSR mode.

Rationale:

- Ecosystem and testing maturity. The frontend is greenfield (ADR-029), so
  ecosystem depth, documentation, hiring familiarity, and Testing Library /
  Playwright support weigh more than incremental fit. This is the same
  reasoning ADR-029 used to choose React itself.
- Mount and progressive takeover. `basename` mounts the SPA under a single
  owned prefix (`/risk-register/`) so the ADR-029 "one SPA host, progressive
  path takeover" model works without rewriting routes: unowned prefixes stay
  Django, the owned prefix serves the shell and the client router resolves
  its sub-paths. Deep links and refresh resolve in both worlds.
- Single origin, no SSR. Library mode is pure client-side, so it preserves
  ADR-029's single-origin posture with no second server and no second CSRF
  or session surface. The framework/SSR (Remix) mode is deliberately not
  used because it would introduce a Node server and a second auth surface.

Rejected alternatives:

- TanStack Router. Strong type-safe routing with first-class typed search
  params (an appealing fit for the URL filter-state requirement below), but
  a smaller ecosystem, a steeper learning curve, and an assumption of
  TanStack Query pairing. It is the runner-up; typed search-param ergonomics
  can be revisited at an ADR-029 addendum if they become a platform priority.
- Wouter. Too minimal for a multi-module platform (weak nested-route and
  route-data patterns, small ecosystem).

### Data fetching and query cache: TanStack Query v5

Decision: TanStack Query (React Query v5) for server state, layered over a
single thin typed fetch client. TanStack Query owns caching, invalidation,
retry, and polling; the typed client owns transport concerns.

Rationale, mapped to the ADR-029 "API client conventions":

- Server state is the dominant state. Risk Register is CRUD plus audit
  reads with almost no long-lived client-only state, so a query cache, not a
  global store, is the right primitive. UI state stays local, honoring the
  "keep UI state separate from domain state" guardrail.
- Invalidation. A risk create/update/close/reopen/delete/restore, or a
  comment add/delete, invalidates the affected list, detail, and audit
  queries so the workspace reflects server truth without manual cache
  surgery.
- Pagination. `PageNumberPagination` (`page`, `PAGE_SIZE 50`) maps to the
  standard `count`/`next`/`previous` paged-query shape.
- Retry policy. Per-query retry covers the ADR-029 rule "auto-retry
  idempotent GETs only, bounded backoff": queries retry with backoff,
  mutations set `retry: 0` and surface the error for explicit user action.
- Polling. Where no websocket exists, `refetchInterval` with a bounded
  interval and no background refetch gives the bounded, cancel-on-unmount
  polling the conventions require. Risk Register has no websocket surface,
  so phase 1 needs no polling; the default is set for later modules.
- Transport-agnostic. The library does not fetch; it calls a supplied
  function. That function is the single typed API client that adds
  `X-CSRFToken` on unsafe methods, relies on the session cookie (no bearer),
  parses the `shared.api.errors` envelope into a typed error, propagates
  `X-Request-ID`, and uses types generated from `/api/v1/schema/`. Every
  ADR-029 client convention lives in that one client, not in components.

Rejected alternatives:

- RTK Query. Excellent when Redux Toolkit is already present; shifter has no
  Redux today, and adopting a global store for data fetching contradicts the
  UI-versus-domain separation guardrail and adds weight this workspace does
  not need.
- SWR. Capable and lighter, but a weaker mutation, invalidation, and
  pagination story for a CRUD-plus-audit workspace.

### How the two compose

React Router owns route and URL state, including the filter/search query
params preserved in the URL (see "UX Flows"). TanStack Query owns server
state keyed by those route and query params. Route loaders stay thin or are
omitted so data fetching lives in query hooks; this avoids duplicating the
cache in the router and keeps one invalidation model. This pairing is the
typed workspace contract described in the "Extensibility Seam" section.

### Formalization

Recommendation: promote both defaults to an ADR-029 addendum in
`docs/adr/index.yaml` so they are enforceable control-plane records with the
same status as the stack choice, rather than design-doc prose. That change
touches guardrail files (`docs/adr/**`) and was scoped out of this design
issue by the preflight, so it is left as a small, explicit follow-up rather
than folded in here. Until it lands, this section is the platform default of
record for later SPA modules.

## Route Map And Required Screens

Client paths should mirror the current information architecture and existing
deep links where practical. Mutating legacy Django form URLs remain
compatibility routes, not SPA data dependencies.

| Workspace area | Client route | Canonical API | Required states |
| --- | --- | --- | --- |
| Risk list | `/risk-register/` | `GET /api/v1/risks/` | loading, loaded, filtered, include-deleted, empty, page error, 401/403 denied |
| Risk detail overview | `/risk-register/risks/:riskId/` | `GET /api/v1/risks/:id/` and `?include_deleted=true` for deleted rows | active, closed, deleted, not found, denied, stale/deleted after load |
| Create risk | `/risk-register/risks/create/` | `POST /api/v1/risks/` | pristine, dirty, submitting, 400 field errors, 401/403 denied, success redirect |
| Edit risk | `/risk-register/risks/:riskId/edit/` | `PATCH /api/v1/risks/:id/` or `PUT /api/v1/risks/:id/` | loaded, dirty, submitting, validation errors, stale/not found, deleted row disabled |
| Close risk | Detail dialog or detail action | Existing API can use `PATCH` status transition; explicit action endpoint is a gap if audit/context parity is required | confirm, resolution reason, submitting, validation/API error, success |
| Reopen risk | Detail dialog or detail action | Existing API can use `PATCH` status transition; explicit action endpoint is a gap if policy/audit parity is required | confirm, submitting, conflict/not closed, success |
| Delete risk | Detail destructive dialog | `DELETE /api/v1/risks/:id/` | confirm, submitting, 204 success, already deleted/stale 404, denied |
| Restore risk | Detail/list action for deleted rows | `POST /api/v1/risks/:id/restore/` | confirm, submitting, 400 not deleted, success, denied |
| Comments | Detail "Comments" tab/section | `GET/POST /api/v1/risks/:riskId/comments/`, `DELETE /api/v1/risks/:riskId/comments/:id/` | list empty, loading, add validation error, delete confirm, deleted-risk read-only |
| Audit/history | Detail "History" tab/section | `GET /api/v1/audit/?entity_type=risk&entity_id=:id` | admin-visible history, empty, loading, denied/not available |

Use contextual subnavigation for one risk: Overview, Mitigation, Comments,
History. List pages should not get breadcrumbs; detail and edit views should
use the IA breadcrumb shape `Govern > Risks > Risk`.

## Data Requirements

Risk list rows need: `id`, `title`, `severity`, `status`, `risk_score`,
`comment_count`, `updated_at`, and `is_deleted`.

Risk detail needs the full `RiskSerializer` payload:

- title, description, severity, status
- STRIDE categories
- likelihood, impact, and computed risk score
- attack vector, affected assets, mitigation status, resolution reason
- created/updated timestamps and deleted state

Create and edit forms submit only fields accepted by `RiskCreateSerializer` and
`RiskUpdateSerializer`. Backend validation is authoritative; client-side
checks may cover required fields and numeric affordances for responsiveness
only.

Comments need `id`, `risk_id`, `content`, `author`, `parent_comment_id`, and
`created_at`. The current comment API is append/delete only; edit, reply,
restore, and threading UI are out of scope unless the backend grows matching
behavior.

Audit visibility uses `AuditLogSerializer` fields. Show concise event rows from
`entity_type`, `action`, `actor_type`, `actor_id`, `timestamp`, `request_id`,
and a bounded before/after summary. Do not render raw JSON blobs by default.

## UX Flows

- Filtering: support severity, status, and show-deleted because the API already
  supports `severity`, `status`, and `include_deleted=true`. Preserve filters in
  the URL query so refresh and share links keep state.
- Sorting/search: do not expose free-form sorting or search unless the backend
  contract is explicit. If sorting ships, use an allowlisted API query and a
  sortable table header with announced sort direction.
- Empty states: distinguish "no risks exist" from "no risks match filters" and
  keep the primary create action available when authorized.
- Destructive actions: delete and comment delete require a design-system
  destructive dialog with focus trap, `Esc` close, return focus, and an
  explicit destructive button. Do not use browser `confirm()`.
- Restore: deleted rows remain visibly distinct and actions are limited to
  restore and read-only inspection. Restoring is a confirmatory action and
  routes through `POST /restore/`.
- Validation errors: map the shared DRF error envelope `details` to field
  messages, mark fields with `aria-invalid`, move focus to the first invalid
  field, and preserve entered values.
- Permission-denied: 401 redirects to Django login through the shared auth
  flow. 403 renders an access-denied workspace state and does not leak whether
  a specific risk ID exists.
- Deleted/stale state: a 404 after a previously loaded row should become a
  non-destructive stale-state message with a link back to the list, not a
  client-side retry loop.

## Layout And Component Mapping

The workspace composes shared design-system primitives only:

| Need | Shared primitive |
| --- | --- |
| Shell, top bar, side navigation | SPA shell primitives from #1299/#1300, role-aware IA contract |
| Page title, subtitle, primary actions | Page header and action slots |
| List filters | Field wrapper, select, checkbox/switch, button group |
| Risk table | Data table with sortable header state if backend sorting exists |
| Severity/status | `.ds-badge` / `.ds-status` intent mappings |
| Detail sections | Key-value detail panel and section layout |
| Forms | Text input, textarea, select, checkbox group, field error |
| Comments | List item/comment row composed from text, metadata, and icon buttons |
| Delete/restore/close dialogs | Dialog and destructive/confirm button variants |
| API errors | Alert/banner plus field-level errors |
| Loading/empty | Skeleton, spinner, empty state primitives |

Risk severity maps to design-system intents already defined by #1299:
critical -> danger, high -> warning, medium -> info, low -> neutral. Risk
status should map by meaning, not color alone: open/acknowledged/mitigating are
active operational states, resolved/closed are terminal or neutral states, and
deleted is a separate soft-delete affordance rather than a status color.

## Accessibility And Keyboard Model

- The risk table uses semantic table markup. Sortable headers are buttons with
  `aria-sort` only when sorting is backed by the API. Row navigation must not
  make the whole row an inaccessible click target; keep a named link in the
  title cell.
- Filters are ordinary labeled controls. Filter changes should either apply via
  an explicit Apply button or announce automatic updates through a polite live
  region.
- Dialogs follow the design-system dialog contract: focus trap, labelled title,
  described consequence text, `Esc` close, return focus, and no background
  interaction while open.
- Forms associate labels, help text, and errors with controls through
  `aria-describedby`. Required state must be programmatic and not conveyed by
  `*` alone.
- Comment actions must be reachable by keyboard and have accessible names that
  include the action and target context, for example deleting a specific
  comment timestamp/author.
- Async submit and loading states set `aria-busy` where appropriate and do not
  move focus unexpectedly except after validation failure or route change.
- Status, severity, deleted state, and permission-denied state must be conveyed
  by text and structure, not color alone.

## Rollout And Route Compatibility

For this design issue, do not change routes.

Recommended rollout for the implementation issue:

- Keep existing Django `risk_register.urls` active until the Risk Register
  implementation issue explicitly authorizes path takeover.
- During any canary/preview period, mount the SPA host on a non-shadowing path
  or behind the SPA feature-flag/bootstrap mechanism from #1300, so existing
  `/risk-register/` links keep rendering Django templates.
- At explicit cutover, route GET page paths to the SPA host while preserving or
  redirecting legacy POST action URLs long enough for old pages, open tabs, and
  bookmarks to fail safely. The SPA itself must use `/api/v1/`, not those
  compatibility URLs.
- Preserve current deep-link shapes for list, detail, create, and edit unless a
  module-specific issue approves redirects. Existing action URLs
  (`delete/`, `restore/`, `close/`, `reopen/`, comment add/delete) should not
  become new SPA data endpoints.

## Backend/API Gaps

These gaps must be explicit before implementation. Non-trivial gaps should be
tracked as follow-up issues rather than hidden behind frontend conditionals.

| Gap | Why it matters | Disposition |
| --- | --- | --- |
| Session/bootstrap endpoint from #1300 | SPA shell needs current principal, permissions, feature flags, and `can_access_risk_register` replacement for `shared.context_processors.user_permissions`. | Required before production SPA route ownership. Track under SPA bootstrap work if not already covered. |
| Explicit risk search/sort query contract | Current list supports `status`, `severity`, and `include_deleted`; search is absent, and ordering should not rely on implicit DRF defaults. | If phase 1 includes search/sort, file a backend follow-up with allowlisted fields and tests. Otherwise omit those controls. |
| STRIDE validation parity | `RiskSerializer` validates STRIDE categories, but create/update serializers currently do not define the same validator. | Backend fix required before trusting SPA create/edit. Keep it server-side, preferably through a shared serializer mixin/helper. |
| Close/reopen action semantics | `PATCH` can change `status` and audit close/reopen by transition, but there are no explicit DRF actions matching Django `close`/`reopen` forms or close `context` handling. | Decide before build: use PATCH as the contract, or file a small backend action follow-up. Do not encode close/reopen policy only in React. |
| Comment pagination | `CommentViewSet.list` returns an unpaginated array, unlike Risk and AuditLog viewsets. | If long comment threads are plausible for phase 1, file a backend pagination follow-up. Otherwise document bounded phase-1 behavior. |
| Unified per-risk history | Risk audit rows are easy to query by `entity_type=risk&entity_id`; full comment history for a risk requires comment IDs/client fan-out and delete rows have limited risk context. | If History must include comment actions in phase 1, file a risk-scoped audit query follow-up. Otherwise show risk entity history only. |
| Runtime choice metadata | OpenAPI exposes enum values for generated types, but runtime label metadata is not a dedicated endpoint. | Use generated types and SPA i18n labels for fixed phase-1 choices. File metadata work only if choices become runtime-configurable. |

### Recommended Follow-Up Issues

The non-trivial gaps split into these follow-up issues. They are scoped here
so the design "splits" them per the acceptance criteria; opening the GitHub
issues is an outward action left to maintainer confirmation.

1. Backend: STRIDE category validation parity in `RiskCreateSerializer` and
   `RiskUpdateSerializer`. `RiskSerializer.validate_stride_categories`
   already exists, but create/update do not enforce it. Move the validator
   to a shared serializer mixin so all three share one rule. Small and
   self-contained; do before trusting SPA create/edit.
2. Backend: explicit Risk list search and ordering contract. Add allowlisted
   `search` (title/description) and `ordering` params (`created_at`,
   `updated_at`, `severity`, `status`, `risk_score`) with tests, so the SPA
   offers search/sort without relying on implicit DRF defaults. Include only
   if phase 1 needs it.
3. Backend: close/reopen contract. The Django UI has `close/` and `reopen/`
   form URLs with resolution-reason and context handling; the DRF API infers
   close/reopen from a `PATCH` on `status`. Either document `PATCH status` as
   the contract or add explicit DRF actions, so close/reopen policy and audit
   context are not encoded only in React.
4. Backend: comment pagination. `CommentViewSet.list` returns an unpaginated
   array, unlike the Risk and AuditLog viewsets. Align it with
   `PageNumberPagination` if long threads are plausible, or document bounded
   phase-1 behavior.
5. Backend: unified per-risk history. If the History view must include
   comment actions (not just risk-entity audit rows), add a risk-scoped audit
   query so the SPA does not fan out per comment id.
6. Backend, cross-module: the #1300 session/bootstrap `/api/v1/` endpoint.
   Required before production SPA route ownership; likely tracked with the
   SPA bootstrap work rather than as a Risk-Register-specific issue.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail for #1301 |
| --- | --- | --- |
| SPA architecture | ADR-029 and `spa-cutover-architecture-1300.md` | Stay single-origin, static built, `/api/v1/` only, session+CSRF for browser calls. |
| Design system | `spa-design-system-foundation-1299.md`, `docs/design/design-system/tokens.css`, `components.css` | Compose shared primitives; no Risk Register-only palette, buttons, tables, dialogs, badges, or shell. |
| IA and routes | `ux-003-information-architecture-sitemap.md`, current `risk_register/urls.py` | Preserve `Govern > Risks > Risk` mental model and existing deep links during rollout. |
| API mount/schema | `config/api_urls.py`, `/api/v1/schema/`, drf-spectacular | Use the canonical v1 mount and generated schema. No app-local API docs or duplicate endpoint family. |
| DRF auth/errors/pagination | `config/_drf_settings.py`, `shared.api.errors`, `PageNumberPagination` | Shared envelope, request id, and pagination shape for paged endpoints. Do not add feature-local exception shapes. |
| Browser CSRF | `CsrfViewMiddleware`, DRF `SessionAuthentication`, existing JS cookie/header pattern | Unsafe SPA requests send `X-CSRFToken`; no `csrf_exempt` and no bearer token in browser state. |
| Programmatic token scopes | `shared.api_tokens.authentication`, `scopes.RISK_READ`, `RISK_WRITE`, `require_scope` | Keep exact central scopes. No wildcard strings or local token checks. |
| Risk authorization | `risk_register.access`, `HasRiskRegisterCognitoGroup`, `IsStaffSessionOrToken`, `IsAdminUser` | UI permission state is advisory; endpoints remain authoritative and fail closed when groups are unset. |
| Risk persistence | `Risk`, `Comment`, `AuditLog`, `shared.db.SoftDeleteManager` | Respect active-only default managers and explicit `include_deleted`/restore flows. |
| Risk validation | `RiskCreateSerializer`, `RiskUpdateSerializer`, model choices, serializer validators | Backend remains source of truth. Frontend validation mirrors for ergonomics only. |
| Audit writes | `risk_register.services.audit_log_from_request`, `AuditEvent`, `RequestAudit`, `get_client_ip`, `get_request_id` | New backend mutations should use the service facade, trusted IP resolver, and request-id capture. Do not add another audit helper. |
| Logging/redaction | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint` | Log IDs, action names, status, and request ids only. Do not log risk bodies, comments, tokens, cookies, or raw envelopes. |
| Tests | `tests/risk_register`, `tests/shared/test_api_errors.py`, SPA test strategy in #1300 | Keep DRF behavior covered with `APIClient`; future SPA uses Vitest/RTL/Playwright and axe per #1300. |
| Architecture gates | `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`, `scripts/adr_guard/adr_guard.py` | Do not weaken CI, import boundaries, generated-asset policy, or ADR guardrails. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: browser requests use Django sessions and DRF
  `SessionAuthentication`; unsafe methods send `X-CSRFToken`. Programmatic
  requests use `Authorization: Bearer shf_...` through
  `ApiTokenAuthentication`. A bad bearer token fails closed and must not fall
  through to a session.
- Authorization surface: risk-register access requires configured Cognito
  groups through `principal_has_risk_register_access`; session mutations also
  require staff/superuser via `IsStaffSessionOrToken`; token mutations require
  `risk:write`; audit reads require admin session. SPA state never widens this.
- Secret-handling surface: session cookies, CSRF tokens, bearer tokens,
  presigned URLs from other modules, risk descriptions, comments, and audit
  before/after blobs must stay out of localStorage, logs, URL query strings,
  process argv, static bundles, schema examples, GitHub metadata, and broad
  screenshots.
- Config/env surface: this design should not add env bindings. Existing
  `RISK_REGISTER_ALLOWED_COGNITO_GROUPS`, DRF settings, CSRF settings,
  staticfiles settings, and audit proxy-hop settings remain server-owned. If a
  future public SPA setting is needed, bind it through the #1300 bootstrap
  path, not a secret-bearing build-time variable.
- Static asset surface: SPA bundles and design-system assets are public,
  cacheable static files served by WhiteNoise. They must contain no tenant
  identifiers, live cloud identifiers, secrets, tokens, or per-user bootstrap
  JSON.
- Payload/schema validation surface: HTTP bodies and query params are validated
  by DRF serializers/filter code. Model choices and serializer validators define
  allowed values. The SPA may prevent obvious empty submits, but server
  validation remains decisive.
- Error-envelope surface: non-2xx API responses use
  `{"error": {"code", "message", "details?", "request_id?"}}` from
  `shared.api.errors`. UI surfaces safe `message`, maps `details` to fields,
  and records `request_id` for support. It must not render raw exception text,
  stack traces, SQL errors, provider payloads, cookies, tokens, or full audit
  JSON.
- Audit/observability surface: audit rows remain in `AuditLog`; request
  correlation comes from `RequestIDMiddleware`. New backend write paths use
  `risk_register.services` rather than direct `AuditLog.log()` calls.
- OS/runtime exposure: the design does not require shell commands, background
  workers, temp files, Terraform, Kubernetes, or cloud CLI calls. Do not pass
  credentials, cookies, tokens, or risk payloads through npm scripts, test
  process arguments, CI summaries, or generated artifacts.
- Import-boundary surface: frontend code is outside the Python import graph.
  Any backend helper added for Risk Register must use `shared` contracts and
  app-local public facades without cross-app model imports or duplicate shared
  DTOs.
- i18n/a11y surface: SPA strings need the translation/extraction path chosen
  by #1300. Accessible names and translated labels must not drift from form
  validation and API error display.

## Extensibility Seam

The reusable seam is a typed Risk Register workspace contract:

- route state: list, risk detail, edit/create, comments, history
- query state: page, severity, status, include-deleted, optional ordering and
  search only when backend-owned
- actor state: authenticated principal, risk-register access, admin history
  visibility
- mutation commands: create, update, close, reopen, delete, restore, add
  comment, delete comment
- rendering mappings: domain status/severity/deleted state to design-system
  intent plus text

Keep this seam in the shared API client and route state, not scattered across
individual components. The next likely modules should reuse the same envelope,
pagination, CSRF, permission-denied, dialog, form-error, and table patterns.
The next likely Risk Register additions - search, explicit close/reopen
actions, comment pagination, risk-scoped history, CSV export, or runtime choice
metadata - should extend this seam without rewriting shared primitives or
forking the API client.

## Whole-Repo Scope

Implementation should consider these surfaces, even if it edits only a subset:

- ADR and design contracts: `docs/adr/index.yaml` ADR-029,
  `docs/architecture/spa-cutover-architecture-1300.md`,
  `docs/design/spa-design-system-foundation-1299.md`,
  `docs/design/ux-003-information-architecture-sitemap.md`.
- Risk Register backend:
  `shifter/shifter_platform/risk_register/models.py`,
  `api/serializers.py`, `api/views.py`, `api/permissions.py`, `api/urls.py`,
  `access.py`, `services.py`, and `urls.py`.
- Existing Risk Register templates for parity only:
  `templates/risk_register/risk_list.html`, `risk_detail.html`,
  `risk_form.html`, and `base.html`.
- Shared platform backend:
  `config/api_urls.py`, `config/_drf_settings.py`, `config/middleware.py`,
  `shared/api/errors.py`, `shared/api/schema.py`, `shared/api_tokens/**`,
  `shared/context_processors.py`, `shared/db/**`, and
  `shared/log_sanitize.py`.
- Static/frontend quality:
  `shifter/shifter_platform/package.json`, `eslint.config.js`,
  `.stylelintrc.json`, existing `static/js` CSRF patterns, and the future SPA
  workspace from ADR-029.
- Tests:
  `tests/risk_register`, `tests/shared`, `tests/config/test_api_urls.py`, and
  future SPA unit/component/e2e tests required by #1300.
- Repo gates:
  `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`,
  `.github/workflows/_quality.yml`, and `scripts/adr_guard/adr_guard.py`.

## Gotchas And Anti-Patterns

- Do not create a Risk Register-specific component library, palette, badge
  scheme, table, dialog, form wrapper, or shell.
- Do not hard-code API enums or response DTOs by hand when `/api/v1/schema/`
  can generate types.
- Do not add local exception classes or frontend error envelopes for risk
  errors. Use the shared DRF envelope.
- Do not implement risk close/reopen/delete/restore as frontend-only status
  edits without backend validation and audit semantics.
- Do not rely on client filters to hide deleted rows or unauthorized actions.
  The API's active-only/default manager and permission classes are the boundary.
- Do not render comments, descriptions, mitigation text, or audit JSON as HTML.
- Do not put `shf_` API tokens, CSRF tokens, cookies, or risk payloads in
  localStorage, URLs, logs, generated bundles, screenshots, or story fixtures.
- Do not use unbounded client fan-out for audit history or comments when a
  backend query shape is missing.
- Do not add app-local `/risk-register/api/` or ad hoc JSON endpoints to make a
  component easier to build.
- Do not weaken existing Django routes during rollout; cutover and retirement
  require an explicit module issue.

## Non-Goals

- Implementing the SPA, frontend workspace, route host, backend gaps, tests, or
  route cutover in this issue.
- Retiring, redirecting, or modifying existing `/risk-register/` Django routes.
- Replacing Risk Register models, soft-delete behavior, audit storage, Cognito
  group policy, API-token scope semantics, or DRF error handling.
- Adding comment edit/reply/restore, risk export, bulk actions, live updates,
  saved views, runtime-configurable risk taxonomies, or a new audit analytics
  surface.
- Introducing new infrastructure, environment variables, secrets, background
  workers, Terraform, Kubernetes, SSR, a second origin, or a second API family.
