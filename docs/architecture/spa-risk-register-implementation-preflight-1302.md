# SPA Risk Register Implementation Preflight (#1302)

Status: pre-implementation guidance

Date: 2026-07-05

Issue: GitHub #1302, "SPA phase 1 implementation: Risk Register workspace"

Requirement: none. The GitHub issue title, body, constraints, and acceptance
criteria are the shipping contract. This note is not an implementation plan and
does not implement the SPA module.

## Scope Boundary

Issue #1302 should implement the first SPA module without changing the
repository's security or domain boundaries. The module must conform to:

- `docs/adr/index.yaml` ADR-029.
- `docs/architecture/spa-cutover-architecture-1300.md`.
- `docs/design/spa-design-system-foundation-1299.md`.
- `docs/design/spa-risk-register-workspace-1301.md`.
- `docs/design/design-system/`.

No new ADR is required unless implementation changes the frontend stack,
router/query-cache defaults, API boundary, auth posture, route-retirement
policy, static-asset policy, CI guardrails, import/layer rules, or documented
Risk Register audit/soft-delete semantics.

The SPA may own presentation, route state, user interaction, typed API calls,
loading/error/empty states, focus management, and rollback-safe compatibility
behavior. It must not own authorization, serializer validation, audit policy,
soft-delete semantics, close/reopen workflow policy, or durable persistence.

## Architecture Decisions And Guardrails

- Build within the ADR-029 SPA architecture: React 18, TypeScript, Vite,
  Django staticfiles/WhiteNoise, one origin, no SSR server, no committed build
  output, and no browser-held `shf_` API tokens.
- Use React Router v7 library/data-router mode and TanStack Query v5 as chosen
  by the #1301 design. Router state owns the URL; TanStack Query owns server
  state. Do not introduce a second store or router for Risk Register.
- Route all data access through the canonical `/api/v1/` surface:
  `/api/v1/risks/`, `/api/v1/risks/:id/`, `/api/v1/risks/:id/restore/`,
  `/api/v1/risks/:riskId/comments/`,
  `/api/v1/risks/:riskId/comments/:id/`, and `/api/v1/audit/`.
- Keep existing `/risk-register/` Django template routes available until a
  module-specific route-retirement issue explicitly removes them. If #1302
  takes over GET page routes, keep legacy POST form URLs as compatibility
  redirects or safe failures long enough for old tabs and bookmarks.
- Preserve session-authenticated unsafe requests: the SPA host primes the CSRF
  cookie, the API client sends `X-CSRFToken` for unsafe methods, and no view is
  marked `csrf_exempt`.
- Generate TypeScript request/response types from `/api/v1/schema/`. Do not
  hand-copy Risk, Comment, AuditLog, status, severity, STRIDE, pagination, or
  error-envelope schemas into feature code.
- Keep backend validation authoritative. Client validation may improve form
  responsiveness, but DRF serializer errors and the shared envelope drive final
  field errors.
- Preserve audit semantics. New backend Risk Register mutations should use
  `risk_register.services.audit_log_from_request()` / `audit_log()` so request
  id, trusted source IP, actor, user agent, degraded-audit behavior, and log
  redaction remain centralized. Do not copy existing direct `AuditLog.log()`
  call sites into new code.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1302 |
| --- | --- | --- |
| SPA architecture | ADR-029, `spa-cutover-architecture-1300.md` | One Django origin, static bundle, `/api/v1/` only, session+CSRF for browsers. |
| Risk workspace design | `spa-risk-register-workspace-1301.md` | Treat #1301 as the screen, state, route, and gap contract; do not redesign the module ad hoc. |
| Design system | `docs/design/design-system/tokens.css`, `components.css` | Compose shared primitives for shell, table, forms, alerts, badges, dialogs, loading, and empty states. |
| API mount/schema | `config/api_urls.py`, drf-spectacular `/api/v1/schema/` | Generate client types and keep endpoint paths canonical. |
| DRF auth/errors/pagination | `config/_drf_settings.py`, `shared/api/errors.py`, `RequestIDMiddleware` | Preserve envelope, request-id correlation, `PageNumberPagination`, and auth order. |
| API tokens | `shared/api_tokens.authentication`, `permissions.require_scope`, `scopes.RISK_READ`, `scopes.RISK_WRITE` | Browser code sends no bearer token; token requests remain fail-closed and scoped. |
| Risk authorization | `risk_register.access`, `risk_register.decorators`, `risk_register.api.permissions` | UI permission state is advisory only; endpoints still enforce group, staff/session, admin, and token-scope gates. |
| Persistence and soft delete | `Risk`, `Comment`, `shared.db.SoftDeleteManager`, explicit `all_objects` | Default reads stay active-only; deleted reads/restores require explicit `include_deleted` or restore paths. |
| Serializer validation | `RiskSerializer`, `RiskCreateSerializer`, `RiskUpdateSerializer`, `CommentCreateSerializer` | Fix backend parity gaps in serializers rather than encoding hidden policy in React. |
| Audit writes | `risk_register.services`, `AuditEvent`, `RequestAudit`, `get_client_ip`, `get_request_id` | Keep audit request context, degraded health, and sanitized logging centralized. |
| Compatibility routes | `risk_register.urls`, `risk_register.views`, existing templates | Use for parity and rollback only, not as SPA data endpoints. |
| Frontend quality | `shifter/shifter_platform/package.json`, `eslint.config.js`, #1300 test strategy | Add SPA build/typecheck/unit/e2e checks alongside existing `npm test`; do not remove legacy checks. |
| Architecture gates | `.importlinter`, `.github/workflows/_quality.yml`, `scripts/adr_guard/adr_guard.py` | Any guardrail-file or platform-workflow change must keep ADR enforcement current. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: browser requests rely on Django session cookies and DRF
  `SessionAuthentication`; unsafe methods include `X-CSRFToken`. Programmatic
  requests remain `Authorization: Bearer shf_...` through
  `ApiTokenAuthentication`. A bad bearer token must still fail closed and never
  fall through to session auth.
- Authorization surface: `RISK_REGISTER_ALLOWED_COGNITO_GROUPS`,
  `principal_has_risk_register_access`, `HasRiskRegisterCognitoGroup`,
  `IsStaffSessionOrToken`, `IsAdminUser`, and `require_scope()` remain the
  gates. Feature flags, hidden buttons, disabled controls, and client-side route
  guards do not authorize mutations or audit reads.
- Secret-handling surface: session cookies, CSRF tokens, bearer tokens, risk
  bodies, comments, and audit before/after blobs must stay out of localStorage,
  URLs, logs, static bundles, schema examples, test snapshots, GitHub metadata,
  process argv, and CI summaries.
- Config/env surface: #1302 should not add secret-bearing env variables. Any
  public SPA setting belongs in the #1300 bootstrap payload, not in a
  build-time variable that could inline secrets into public assets.
- Static asset surface: Vite output is public, cacheable static content served
  through Django staticfiles/WhiteNoise. Bundles must contain no per-user data,
  tenant identifiers, live cloud IDs, tokens, or bootstrap JSON.
- Payload/schema validation surface: DRF serializers, model choices, and
  explicit filters validate HTTP payloads and query params. The implementation
  should close the known STRIDE create/update parity gap server-side before
  trusting SPA create/edit flows.
- Error-envelope surface: non-2xx API responses use
  `{"error": {"code", "message", "details?", "request_id?"}}`. UI renders safe
  messages, maps validation `details` to fields, and may show `request_id` for
  support; it must not render raw exception text, SQL errors, stack traces,
  cookies, tokens, or raw audit JSON.
- Audit/observability surface: Risk Register audit rows remain in `AuditLog`;
  request correlation remains `RequestIDMiddleware`; audit source IP remains
  `risk_register.services.get_client_ip()`. Client logs should contain action
  names and request ids only, never risk/comment bodies.
- OS/runtime exposure surface: the SPA module should not introduce shell
  commands, workers, temp files, Terraform, Kubernetes, or cloud CLIs. Test and
  build commands must not pass cookies, tokens, or payloads through argv or
  generated artifacts.
- Import/layer surface: frontend code stays outside the Python import graph.
  Backend additions must use `shared` contracts and Risk Register public
  facades; do not create cross-app model imports or duplicate DTOs.
- Accessibility/i18n surface: design-system form, dialog, alert, table, tab,
  focus, reduced-motion, and keyboard contracts apply. SPA user-facing strings
  need the extraction/translation path chosen by the SPA architecture work.

## Extensibility Seam

Keep the reusable seam in the typed API client, route state, and shared UI
primitives:

- API-client parameters: `page`, `severity`, `status`, `include_deleted`, and
  future backend-owned `search` / `ordering`.
- Route parameters: list filters, risk id, create/edit mode, detail subview
  (`overview`, `mitigation`, `comments`, `history`).
- Actor/permission state: authenticated principal, risk-register access, write
  permission, admin audit visibility, and route-ownership feature flag.
- Mutation commands: create, update, close, reopen, delete, restore, add
  comment, delete comment.
- Rendering mappings: domain severity/status/deleted state to design-system
  intent and text.

The next likely changes are explicit close/reopen DRF actions, risk search and
ordering, comment pagination, risk-scoped history, CSV export, or runtime
choice metadata. They should extend these parameters rather than requiring a
new API client, component library, router, or local schema vocabulary.

## Gotchas And Anti-Patterns

- Do not add app-local `/risk-register/api/` endpoints or non-DRF JSON views.
- Do not call legacy Django form/action URLs from SPA data code.
- Do not retire or shadow `/risk-register/` routes without a documented
  compatibility and rollback path.
- Do not create Risk Register-only buttons, tables, dialogs, badges, alerts,
  form wrappers, status colors, or shell primitives.
- Do not hand-code enums, DTOs, pagination shapes, or error envelopes already
  exposed by the OpenAPI schema and shared DRF error handler.
- Do not encode close/reopen, restore, soft-delete, STRIDE validation, comment
  immutability, or audit-history policy only in frontend code.
- Do not make client filtering the thing that hides deleted rows or protected
  audit details. Backend managers and permissions remain decisive.
- Do not render descriptions, mitigations, affected assets, comments, or audit
  JSON as HTML or Markdown unless a separate sanitizer policy is approved.
- Do not auto-retry unsafe mutations. Retry only idempotent GETs with bounded
  backoff.
- Do not weaken `npm test`, Django tests, static asset conventions, ADR
  guardrails, import-linter rules, or existing DRF token/session tests while
  adding SPA checks.

## Non-Goals

- Implementing the SPA code, frontend workspace, Django SPA host, API client,
  tests, migrations, or route cutover in this preflight.
- Replacing Risk Register models, serializers, permissions, soft-delete
  managers, audit storage, token scopes, or the shared DRF error envelope.
- Replacing existing Django templates/routes before an explicit route-retirement
  issue.
- Adding comment edit/reply/restore, bulk actions, exports, live updates, saved
  views, runtime-configurable risk taxonomies, or audit analytics beyond the
  #1302 contract.
- Introducing SSR, a second origin, CORS, browser API tokens, new cloud/runtime
  infrastructure, new secret delivery, Terraform, Kubernetes, or background
  workers.
