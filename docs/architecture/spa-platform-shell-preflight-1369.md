# SPA Platform Shell Preflight (#1369)

Status: pre-implementation guidance

Date: 2026-07-09

Issue: GitHub #1369, "SPA Phase 2: App shell & global navigation (home,
dashboard, auth)"

Requirement: none. The GitHub issue title, body, constraints, and acceptance
criteria are the shipping contract.

This note sets repo-wide architecture guardrails for the platform shell before
implementation. It is not an implementation plan and does not implement routes,
components, APIs, serializers, tests, feature flags, or a route cutover.

## Scope Boundary

#1369 generalizes the first Risk Register SPA shell into the platform-wide
shell that later Phase 2 modules mount into. It must build on:

- ADR-013: unified information architecture and one shared, role-aware
  navigation contract.
- ADR-029: React 18, TypeScript, Vite, React Router v7, TanStack Query v5, one
  Django origin, canonical `/api/v1/`, session plus CSRF for browser calls, and
  no browser-held `shf_` API tokens.
- `docs/design/spa-cohesive-ux-1368.md` and
  `docs/design/ux-003-information-architecture-sitemap.md`: the maintained
  mode, IA, navigation, layout, and taxonomy source for this shell.
- The existing Tailwind v4 plus shadcn/ui frontend under
  `shifter/shifter_platform/frontend/`, the Apple-dark theme, and the Shifter
  mark/favicons.
- The Risk Register SPA implementation as a reference for build, host, API
  client, bootstrap, error, loading, and access-denied patterns, not as the
  final platform IA.

No new ADR is required if #1369 stays within ADR-013 and ADR-029. Update ADR
docs only if the implementation changes an enforceable guardrail: frontend
stack, auth posture, API boundary, navigation source of truth, route retirement
policy, static asset policy, CI gates, import/layer rules, or documented
exceptions.

## Architecture Decisions And Guardrails

- Build one shared shell boundary. The current
  `frontend/src/components/app-shell.tsx` hardcodes the Risk Register nav and
  must become a platform shell fed by shared metadata, not a second shell per
  module.
- Navigation data belongs behind one shared platform contract. Each entry keeps
  the UX-003 minimum fields (`surface`, `audience`, `route_name`,
  `permission_policy`, `owner_app`, `purpose`) plus #1368 presentation fields
  (`mode`, `group`, `route_path`, `icon_key`, `active_context`, `feature_flag`,
  `children`). Adding a surface adds metadata, not shell branches.
- Mode is not authorization. Participant and operator are UX modes. CTF
  participant, CTF organizer, staff, superuser, Threat Research, risk-register
  access, resource ownership, and token scopes remain backend authorization
  facts.
- Use one router, one query client, one typed fetch client, one generated API
  type surface, and one shared error class. Do not create per-module routers,
  stores, fetch wrappers, DTOs, error envelopes, or validation vocabularies.
- Extend bootstrap only for shell state: principal, advisory permission flags,
  feature flags, mode eligibility, active range/event summaries, and shell
  metadata needed on first paint. Dashboard data with its own freshness or
  aggregation semantics should use a canonical serializer-backed `/api/v1/`
  read endpoint, not build-time globals or client-only heuristics.
- Implement rollout as a reversible, non-secret platform shell flag following
  the Risk Register pattern: read the flag per request, keep legacy Django
  routes available for rollback, and expose the flag through bootstrap. Do not
  inline deployment state through Vite build-time variables.
- Preserve provider-driven authentication. `platform_login`,
  `identity_platform_session`, OIDC/Cognito, dev-login, CTF magic links, and
  `logout_view` remain server/provider flows. Auth-adjacent SPA surfaces may
  present logged-out, login landing, and access-denied states, but must not move
  password handling, ID-token verification, MFA policy, or logout provider
  behavior into React.
- Keep home/dashboard production-grade but bounded. The first authenticated
  screen should be a usable operational dashboard, not a marketing page or
  placeholder. It should summarize existing domain facts without inventing new
  durable workflow states.
- Accessibility AA is part of the shell contract: skip link, `banner`/`nav`/
  `main` landmarks, route-change focus management, keyboard navigation, roving
  tabindex for composite nav/menu controls, focus traps for overlays, reduced
  motion, non-color-only status, and safe no-JavaScript fallback copy.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1369 |
| --- | --- | --- |
| IA and navigation | ADR-013; `docs/design/ux-003-information-architecture-sitemap.md`; `docs/design/spa-cohesive-ux-1368.md` | Derive shell nav, breadcrumbs, mode switching, and contextual subnav from one shared contract. |
| SPA stack | ADR-029; `docs/architecture/spa-cutover-architecture-1300.md`; `frontend/src/main.tsx`; `frontend/src/router.tsx` | Keep React Router v7 and TanStack Query. Do not introduce SSR, another origin, or another router/store. |
| Shell reference | `frontend/src/components/app-shell.tsx`; `frontend/src/app/RootLayout.tsx`; `frontend/src/app/bootstrap-context.tsx` | Generalize these patterns centrally; do not fork module shells. |
| Visual system | `frontend/src/index.css`; `frontend/src/components/ui/*`; `frontend/src/components/logo.tsx`; `frontend/components.json`; `docs/design/spa-design-system-foundation-1299.md` | Reuse Apple-dark Tailwind v4, shadcn/ui primitives, lucide icons, and the Shifter mark. No new visual language. |
| Static SPA host | `shared/spa.py`; `risk_register/spa_views.py`; `templates/spa/risk_register.html`; `risk_register/urls.py` | Preserve Vite manifest resolution, CSRF priming, WhiteNoise static serving, and flag-gated legacy fallback. |
| API mount and schema | `config/api_urls.py`; drf-spectacular `/api/v1/schema/`; `frontend/src/api/schema.d.ts`; `frontend/src/api/types.ts` | Generate types from the API schema. No hand-copied schemas or app-local JSON endpoints. |
| Fetch/errors/cache | `frontend/src/api/client.ts`; `frontend/src/api/errors.ts`; `frontend/src/api/queryClient.ts`; `shared/api/errors.py`; `config/_drf_settings.py` | Keep `/api/v1`, same-origin credentials, CSRF header, request-id propagation, shared error envelope, and bounded GET retry. |
| Bootstrap and context | `shared/api/bootstrap.py`; `shared.context_processors.user_permissions`; `mission_control.context_processors.active_range`; `ctf.context_processors.ctf_navigation` | Move shell-readable context into serializer-backed bootstrap fields and generated types; do not duplicate context processor logic in React. |
| Auth and sessions | `config.views.platform_login`; `identity_platform_session`; `logout_view`; `config._oidc_settings`; `config._drf_settings`; `shared/api_tokens.authentication` | Browser auth remains Django session plus CSRF. API tokens remain programmatic only. |
| Authorization | `shared.auth`; `mission_control.api.permissions`; `cms.api.permissions`; `risk_register.access`; `risk_register.api.permissions`; CTF bridges and API checks | Navigation visibility is advisory. Endpoint permission classes and service-layer checks stay authoritative. |
| Validation and domain state | DRF serializers; `shared.schemas`; `cms.scenarios.schema`; upload validators; module services | Shell and dashboard UI may format values, but serializers and services own payload validation and workflow state. |
| Logging and audit | `config.middleware.RequestIDMiddleware`; `config/_logging_config.py`; `shared.log_sanitize`; `shared.errors`; module audit services | Preserve ECS logs, request correlation, safe user messages, and redaction. Do not create a frontend audit vocabulary. |
| Special transports | `mission_control/routing.py`; `config/asgi.py`; Guacamole and upload APIs; CTF file/range APIs | Reuse Channels, Guacamole bootstrap, presigned upload/download, and long-running lifecycle boundaries. No new auth channel. |
| Quality gates | `frontend/package.json`; `frontend/eslint.config.js`; `.github/workflows/_quality.yml`; `scripts/adr_guard/adr_guard.py`; `.importlinter` | Keep SPA lint, typecheck, Vitest/axe, build, Django tests, import-linter, and ADR guardrails intact. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: SPA-owned authenticated routes start after a Django session
  exists. Unsafe requests pass through `CsrfViewMiddleware` and DRF
  `SessionAuthentication` with `X-CSRFToken` from `frontend/src/api/client.ts`.
  Login and logout keep using `config.views` and provider-owned flows.
- API-token surface: `shared.api_tokens.authentication.ApiTokenAuthentication`
  stays fail-closed. Bad bearer tokens must not fall through to a browser
  session, and shell code must never store or send `shf_` tokens.
- Authorization surface: backend checks remain decisive for CTF membership,
  CTF organizer operations, CMS authoring, Mission Control ownership,
  terminal/range access, risk-register group access, staff/admin gates, and
  token scopes. Bootstrap flags and nav metadata are advisory UI state only.
- Secret-handling surface: session cookies, CSRF tokens, ID tokens, bearer
  tokens, invite tokens, presigned URLs, signed Guacamole URLs, credentials,
  private hostnames, live cloud identifiers, challenge flags, provider payloads,
  risk/comment bodies, and audit blobs must not appear in static bundles,
  localStorage/sessionStorage, URLs, logs, schema examples, screenshots,
  test snapshots, GitHub summaries, or process argv.
- Config/env surface: a shell rollout flag is a non-secret boolean in Django
  settings and bootstrap. If a new env binding is added, keep it literal enough
  for `config/_env_manifest.py`, update `config/env-manifest.json`, and add or
  adjust settings tests. Do not use Vite env vars for deployment-owned values.
- Static asset surface: Vite output under `static/spa/` is public, cacheable,
  built in CI/image build, and gitignored. It must contain no per-user,
  tenant, runtime, or secret state.
- Payload/query validation surface: generated TypeScript types come from
  `/api/v1/schema/`; DRF serializers and existing domain schemas validate HTTP
  payloads and query params. Client pre-checks can improve ergonomics but cannot
  replace serializer validation.
- Error-envelope surface: API errors use
  `{"error": {"code", "message", "details?", "request_id?"}}`. The shell may
  render safe messages and request ids, but not raw exception text, SQL/provider
  errors, stack traces, cookies, tokens, signed URLs, or raw audit JSON.
- Logging/observability surface: `X-Request-ID` flows from the SPA client to
  `RequestIDMiddleware` and back on responses. Browser diagnostics should log
  action names and request ids only; server logs use existing ECS formatting and
  `shared.log_sanitize` where user-controlled values appear.
- WebSocket/special-transport surface: terminal, range status, and NGFW status
  sockets remain Django Channels routes using the existing ASGI auth/origin
  stack. No second websocket auth scheme and no client-generated secret channel.
- OS/runtime exposure surface: this shell should not introduce shelling out,
  workers, temp files, Terraform, Kubernetes, or cloud CLIs. Build, test, and
  Playwright commands must not pass cookies, tokens, presigned URLs, or
  credentials through argv or emitted artifacts.
- Import/layer surface: frontend code stays outside the Python import graph.
  Backend additions must respect ADR-001 and `.importlinter`, using `shared`
  contracts and public service facades instead of cross-app model or private
  module imports.
- Accessibility/i18n surface: shell strings and auth-adjacent states need the
  repo's chosen SPA extraction/translation path before broad cutover. Django
  templates still follow ADR-016 with `{% trans %}` / `{% blocktrans %}`.

## Extensibility Seams

- Navigation seam: one metadata source should drive primary nav, mode switch,
  breadcrumbs, contextual subnav, active matching, feature-flag visibility, and
  route ownership. The next surface should register metadata, not edit shell
  internals.
- Bootstrap seam: principal, permission flags, feature flags, mode eligibility,
  active range summary, and active event summary belong in typed bootstrap
  serializers and generated frontend types. This is the shell-state seam.
- Dashboard seam: operational dashboard summaries need a typed, serializer
  owned `/api/v1/` read shape when they are fresher or heavier than bootstrap.
  The summary should compose existing module state, not define new source of
  truth tables or workflow states.
- Route-ownership seam: SPA-owned prefixes should be data-driven enough to add
  Mission Control, Scenario Editor, CTF, Admin, and Risk Register alignment
  without copying the Risk Register URL wrapper. The seam is prefix, flag,
  legacy fallback, SPA host, and client route metadata.
- State-mapping seam: one mapping turns domain statuses and severities into
  design-system intents and accessible labels. New domain values add mappings,
  not new badge components, colors, or state machines.

## Whole-Repo Scope

#1369 implementation should evaluate these surfaces together:

- Architecture/design: ADR-013, ADR-016, ADR-022, ADR-029,
  `docs/design/ux-003-*`, `docs/design/spa-cohesive-ux-1368.md`,
  `docs/design/spa-design-system-foundation-1299.md`,
  `docs/architecture/spa-cutover-architecture-1300.md`, and SPA preflight
  notes.
- Frontend: `shifter/shifter_platform/frontend/package.json`,
  `vite.config.ts`, `components.json`, `src/index.css`, `src/main.tsx`,
  `src/router.tsx`, `src/api/*`, `src/app/*`, `src/components/*`, and
  `src/features/risk-register/*`.
- Django shell/auth/config: `config/urls.py`, `config/api_urls.py`,
  `config/settings.py`, `config/env-manifest.json`, `config/_drf_settings.py`,
  `config/_oidc_settings.py`, `config/views.py`, `config/asgi.py`,
  `config/middleware.py`, and `shared/spa.py`.
- Shared backend contracts: `shared/api/*`, `shared/api_tokens/*`,
  `shared/auth.py`, `shared/context_processors.py`, `shared/errors.py`,
  `shared/log_sanitize.py`, `shared/schemas/*`, `shared/db/*`, and
  `shared/channels/*`.
- Module surfaces: `mission_control/api/*`, `mission_control/routing.py`,
  `mission_control/context_processors.py`, `ctf/api/*`,
  `ctf/views/api/*`, `ctf/context_processors.py`, `cms/api/*`,
  `cms/scenario_editor/*`, `risk_register/api/*`, `risk_register/urls.py`,
  and their service layers.
- Legacy evidence and compatibility surfaces: `templates/**`, `static/css/**`,
  `static/js/**`, especially login/logout templates and existing sidebars.
- Enforcement/workflows if touched: `.github/workflows/**`, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/adr_guard.py`, frontend ESLint/Vitest/Playwright config,
  root/frontend package scripts, and documentation coverage manifest.

## Gotchas And Anti-Patterns

- Do not redesign the locked theme, Tailwind/shadcn foundation, logo, favicon,
  typography, or color language.
- Do not build a marketing landing page as the authenticated product shell.
- Do not create module-local nav constants, shell layouts, fetch clients,
  error classes, DTOs, validation layers, exception hierarchies, status enums,
  or workflow state machines.
- Do not treat Risk Register's first shell as the final all-platform IA.
- Do not use role names as modes or collapse participant and operator surfaces
  into one flat role list.
- Do not make client route guards, hidden links, disabled buttons, bootstrap
  flags, or nav visibility the security boundary.
- Do not call legacy Django form/action URLs or app-local JSON endpoints from
  SPA data code.
- Do not store drafts, tokens, signed URLs, provider payloads, challenge flags,
  credentials, or user-entered sensitive content in localStorage/sessionStorage.
- Do not render user-entered risk text, comments, challenge text, scenario YAML,
  audit JSON, provider messages, or upload metadata as HTML/Markdown unless a
  sanitizer policy is explicitly accepted.
- Do not auto-retry unsafe mutations or destructive long-running actions.
- Do not weaken ADR guard, import-linter, Django i18n, collectstatic, legacy
  Jest/Stylelint, SPA ESLint, Vitest/axe, Playwright, or Docker build gates.

## Non-Goals

- No implementation of SPA routes, shell components, nav registry, feature
  flags, APIs, serializers, migrations, services, tests, or route cutovers in
  this preflight.
- No retirement of legacy Django routes or templates. Route retirement remains
  module-specific and explicitly authorized.
- No replacement of Django sessions, OIDC, Identity Platform, CTF magic links,
  CSRF, API-token auth, DRF permissions, provider login/logout, or provider MFA
  behavior.
- No new runtime secret delivery, Vite secret injection, cloud infrastructure,
  Terraform, Kubernetes, workers, websocket auth scheme, SSR server, second
  origin, or CORS posture.
- No replacement of existing domain services, serializers, schemas, validation,
  exception handling, audit stores, logging format, or persistence policy.
- No per-surface implementation for Mission Control, Scenario Editor, CTF,
  Admin, or Risk Register alignment; those are the dependent module issues.
