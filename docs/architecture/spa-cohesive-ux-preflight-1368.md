# SPA Cohesive UX Preflight (#1368)

Status: pre-implementation guidance

Date: 2026-07-08

Issue: GitHub #1368, "SPA Cutover -- cohesive UX: use cases, IA & wireframes (all surfaces)"

Requirement: none. The GitHub issue title, body, acceptance criteria, and
blocked implementation issues are the shipping contract.

This note sets repo-wide design guardrails before the cohesive UX pass. It is
not an implementation plan and does not implement the SPA, routes, APIs,
components, or wireframes.

## Scope Boundary

#1368 owns a product design artifact: use cases, shared IA, global navigation,
layout/pattern system, all-surface wireframes, major-departure rationale, and
Risk Register alignment notes. It may revise the maintained IA/design artifacts
when the UX pass validates a better model.

It must build on these locked foundations:

- ADR-013: one shared, role-aware platform navigation contract.
- ADR-029: React 18, TypeScript, Vite, React Router v7, TanStack Query v5,
  single Django origin, canonical `/api/v1/`, session plus CSRF for browser
  calls, and no browser-held `shf_` API tokens.
- The existing Tailwind v4 plus shadcn/ui frontend under
  `shifter/shifter_platform/frontend/`.
- The Apple-dark theme and Shifter chevron mark/favicons.
- The SPA design-system and Risk Register foundation docs.

No new ADR is needed for #1368 by itself. Update ADR docs only if the UX pass
changes an enforceable guardrail: frontend stack, API boundary, auth posture,
route-retirement policy, static asset policy, navigation source-of-truth rule,
CI gates, import/layer rules, or a documented exception.

## Architecture Decisions And Guardrails

- Treat `docs/design/ux-003-information-architecture-sitemap.md` as the
  maintained IA/taxonomy source. #1368 may update that artifact after validation,
  but it must not create a competing sitemap, navigation vocabulary, or
  per-surface taxonomy.
- Expand the existing SPA shell concept, do not fork it. The Risk Register shell
  in `frontend/src/components/app-shell.tsx` is a bounded first cut; the
  cohesive design should define the shared platform shell contract that later
  implementation issues extend centrally.
- Navigation data belongs behind one shared platform boundary. A nav item must
  keep the UX-003 minimum contract: `surface`, `audience`, `route_name`,
  `permission_policy`, `owner_app`, and `purpose`. The cohesive pass may add
  presentation fields such as group, icon key, route path, active-context
  target, feature flag, and child/contextual entries, but those additions should
  parameterize one contract rather than create app-local schemas.
- Mode is not role. Participant/Organizer are UX modes; CTF participant,
  CTF organizer, staff, superuser, Threat Research, and risk-register access
  are authorization facts. Wireframes may hide or disable controls for clarity,
  but every backend endpoint and service remains the authority.
- UI status is not domain state. Design-system intents such as danger, warning,
  info, success, and neutral render domain values; they do not define range,
  event, challenge, scenario, risk, upload, Guacamole, or terminal state
  machines.
- Use-case catalog entries should name actor, job, current pain, authoritative
  backend owner, and known API/readiness gaps. Do not invent new durable
  workflow states when existing services, models, serializers, or context
  processors already own them.
- Wireframes must include operational states, not only happy paths: loading,
  empty, filtered-empty, permission denied, validation error, backend error with
  request id, stale/not found, long-running, degraded/offline, destructive
  confirmation, read-only/deleted, and no-JavaScript where applicable.
- Risk Register alignment notes are deltas from the current #1301/#1302 design.
  Do not make Risk Register the visual template for every surface; use it as the
  first validated module and adjust it when the all-surface system requires.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1368 |
| --- | --- | --- |
| IA and taxonomy | ADR-013; `docs/design/ux-003-information-architecture-sitemap.md`; `docs/design/ux-003-oss-shifter-research-personas.md` | Update the maintained artifact if the cohesive pass changes IA. Do not add a second sitemap or module-local vocabulary. |
| Visual system | `frontend/src/index.css`; `frontend/components.json`; `frontend/src/components/ui/*`; `frontend/src/components/logo.tsx`; `docs/design/spa-design-system-foundation-1299.md` | Use Tailwind v4, shadcn/ui, lucide icons, the existing Apple-dark token direction, and the Shifter mark. No new theme or logo. |
| SPA architecture | ADR-029; `docs/architecture/spa-cutover-architecture-1300.md`; `frontend/src/router.tsx`; `frontend/src/api/client.ts`; `frontend/src/api/queryClient.ts`; `frontend/src/app/bootstrap-context.tsx` | One router, one query-cache policy, one typed fetch client, one generated OpenAPI type surface. Do not add per-surface clients or stores. |
| Bootstrap and shell state | `shared/api/bootstrap.py`; `shared.context_processors.user_permissions`; `mission_control.context_processors.active_range`; `ctf.context_processors.ctf_navigation` | Shell metadata, modes, permission flags, and active range/event summaries should extend bootstrap serializers/generated types, not frontend-only constants. |
| API mount and schema | `config/api_urls.py`; `/api/v1/schema/`; module API URL files under `risk_register/api`, `mission_control/api`, `ctf/api`, `cms/api` | Wireframes should be buildable against `/api/v1/`. App-local HTML routes and legacy JSON helpers are compatibility surfaces, not SPA data contracts. |
| Auth and sessions | `config.views.platform_login`; `identity_platform_session`; `logout_view`; `config._drf_settings`; `shared.api_tokens.authentication` | Provider login remains server/provider-driven. Browser calls use session cookies plus `X-CSRFToken`; API tokens stay programmatic only. |
| Authorization | `shared.auth`; `risk_register.access`; `risk_register.api.permissions`; `mission_control.api.permissions`; CTF access predicates and bridges; CMS authoring checks | Navigation visibility and disabled controls are advisory. Endpoint permission classes and service ownership checks remain decisive. |
| Validation and schemas | DRF serializers; generated `frontend/src/api/schema.d.ts`; `shared.schemas`; `cms/scenarios/schema.py`; upload validators | Client affordances may pre-check form shape, but authoritative validation stays in serializers/domain schemas. Do not hand-copy DTOs or enums. |
| Errors | `shared/api/errors.py`; `shared.errors`; `frontend/src/api/errors.ts`; `frontend/src/api/client.ts` | Use the shared error envelope and safe message classification. UI may show safe message plus request id, not raw exception text. |
| Logging and audit | `config.middleware.RequestIDMiddleware`; `config/_logging_config.py`; `shared.log_sanitize`; `risk_register.services`; `shared.api_tokens.audit` | Preserve request-id correlation and redaction. The UX pass should not define a second audit/log vocabulary. |
| Static SPA hosting | `shared/spa.py`; `risk_register/spa_views.py`; `templates/spa/risk_register.html`; `config/settings.py` staticfiles/WhiteNoise | Static assets are public build artifacts. No committed Vite output, no per-user bootstrap data in bundles, no second origin. |
| Legacy coexistence | `risk_register/urls.py` rollout flag pattern; Django base templates and static CSS under `templates/**` and `static/css/**` | Design for phased takeover. Legacy page routes remain until module-specific issues retire them. |
| Special flows | `mission_control/api/guacamole.py`; `mission_control/routing.py`; `config/asgi.py`; upload APIs; CTF file/invite/range APIs | Wireframes must reuse existing Guacamole, websocket, upload, download, invite, and long-running lifecycle boundaries instead of defining new transports. |
| Quality gates | `frontend/package.json`; root `package.json`; `eslint.config.js`; `.stylelintrc.json`; `.importlinter`; `scripts/adr_guard/adr_guard.py` | Add or extend checks only through the existing gate surfaces. Do not weaken legacy JS/CSS/Python checks while adding SPA checks. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: login, Identity Platform session exchange, OIDC, dev-login, CTF
  magic-link paths, and logout remain server/provider flows. SPA-owned
  authenticated pages start after a Django session exists; unsafe API calls go
  through `CsrfViewMiddleware` and DRF `SessionAuthentication` with
  `X-CSRFToken`.
- API-token surface: `ApiTokenAuthentication` remains fail-closed. A supplied
  bad bearer token must not fall through to a logged-in browser session, and the
  browser SPA must never store or send `shf_` tokens.
- Domain authorization surface: CTF event membership, organizer rights,
  challenge availability, CMS authoring rights, Mission Control ownership,
  terminal/range ownership, risk-register group access, staff/admin gates, and
  token scopes remain backend checks. The UX model may expose advisory
  permission flags only.
- Secret-handling surface: session cookies, CSRF tokens, bearer tokens, ID
  tokens, invite tokens, upload tokens, presigned URLs, signed Guacamole URLs,
  credentials, private hostnames, live cloud identifiers, challenge flags, and
  provider payloads must not appear in wireframe fixtures, screenshots, static
  bundles, localStorage, URLs, logs, error messages, test snapshots, GitHub
  summaries, process argv, or schema examples.
- Config/env surface: #1368 should not add environment bindings. If a later
  implementation needs public runtime UI configuration, prefer the bootstrap
  payload and documented serializers; secret or deployment-owned values must
  stay out of Vite build-time variables.
- Payload and query validation surface: generated TypeScript types come from
  `/api/v1/schema/`; DRF serializers validate HTTP shapes; existing domain
  schemas and services validate scenarios, uploads, credentials, range specs,
  CTF workflows, and risk data. Do not split one business rule between the
  client and backend.
- Error-envelope surface: non-2xx API responses use the shared envelope
  `{"error": {"code", "message", "details?", "request_id?"}}`. Wireframes
  should include safe page, field, and toast/banner treatments without rendering
  stack traces, SQL/provider errors, tokens, cookies, signed URLs, or raw audit
  blobs.
- WebSocket/special-transport surface: terminal, range status, and NGFW status
  sockets remain Django Channels routes protected by `AllowedHostsOriginValidator`
  and `AuthMiddlewareStack`. Do not introduce a second websocket auth scheme or
  client-generated secret channel.
- Static asset surface: Tailwind output, shadcn components, icons, images, and
  Vite bundles are public cacheable assets served through Django staticfiles and
  WhiteNoise. They must contain no per-user state, tenant data, live cloud IDs,
  or secret-bearing URLs.
- OS/runtime exposure surface: Node scripts, Playwright commands, management
  commands, local demos, CI logs, and generated reports must not carry cookies,
  bearer tokens, CSRF tokens, provider tokens, presigned URLs, or credentials in
  argv or emitted artifacts.
- Logging/observability surface: server logs stay ECS-formatted and sanitized;
  request correlation flows through `X-Request-ID` / `RequestIDMiddleware`.
  Browser diagnostics should be generic and secret-free.
- Accessibility/i18n surface: AA accessibility is part of the wireframe
  contract: semantic landmarks, skip link, keyboard paths, focus order, focus
  traps, accessible names, form-error linkage, non-color-only status, reduced
  motion, and contrast. Django template strings remain under ADR-016; SPA
  strings need an explicit extraction/translation path before broad cutover.
- Import/layer surface: frontend code stays outside the Python import graph.
  Backend work implied by wireframes must respect ADR-001 and `.importlinter`:
  apps call public service facades and shared contracts, not each other's models
  or private modules.

## Extensibility Seams

- Navigation seam: centralize surface metadata and derive shell nav,
  breadcrumbs, contextual subnav, mode switching, and route ownership from that
  metadata. Required parameters are mode/audience, route, permission policy,
  owner app, feature flag, active context, icon key, and children. Adding a new
  surface should add one metadata entry, not edit every shell component.
- Bootstrap seam: current principal, permission flags, feature flags, and active
  range/event summaries should extend `BootstrapSerializer` and generated
  `Bootstrap` types. Avoid build-time globals and client-only role heuristics.
- Layout seam: wireframes should define reusable page templates and shell slots
  for overview, list, detail, editor, terminal/workspace, admin table, and
  destructive confirmation. Feature modules fill slots with domain data; they do
  not invent new shells.
- State-mapping seam: keep one mapping from domain statuses/severities to
  design-system intents and accessible labels. The next status value should add
  one mapping, not new badge components or color tokens.
- API-readiness seam: keep a surface capability matrix that records canonical
  API availability, serializer maturity, special transports, route ownership,
  and known backend gaps. Per-surface implementation issues should consume that
  matrix instead of rediscovering gaps.

## Whole-Repo Scope

The cohesive UX pass should evaluate these surfaces together:

- Architecture/design docs: ADR-013, ADR-016, ADR-029,
  `docs/design/ux-003-*`, `docs/design/spa-design-system-foundation-1299.md`,
  `docs/design/spa-risk-register-workspace-1301.md`, and SPA preflight notes.
- Frontend: `shifter/shifter_platform/frontend/package.json`,
  `components.json`, `src/index.css`, `src/router.tsx`, `src/api/*`,
  `src/app/*`, `src/components/*`, and `src/features/risk-register/*`.
- Django shell/auth/config: `config/urls.py`, `config/api_urls.py`,
  `config/settings.py`, `config/_drf_settings.py`, `config/views.py`,
  `config/asgi.py`, `config/middleware.py`, and `shared/spa.py`.
- Shared backend contracts: `shared/api/*`, `shared/api_tokens/*`,
  `shared/auth.py`, `shared/context_processors.py`, `shared/errors.py`,
  `shared/log_sanitize.py`, `shared/schemas/*`, `shared/db/*`, and
  `shared/channels/*`.
- Module surfaces: `mission_control/api/*`, `mission_control/routing.py`,
  `mission_control/context_processors.py`, `ctf/api/*`, `ctf/views/api/*`,
  `ctf/context_processors.py`, `cms/api/*`, `cms/scenario_editor/*`,
  `risk_register/api/*`, `risk_register/urls.py`, and their services.
- Legacy templates/static assets for migration evidence only:
  `templates/**`, `static/css/**`, `static/js/**`.
- Enforcement and workflow surfaces when checks change: `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/adr_guard.py`, `frontend/eslint.config.js`,
  `.stylelintrc.json`, root/frontend package scripts, and
  `.github/workflows/**`.

## Gotchas And Anti-Patterns

- Do not redesign the locked theme, Tailwind/shadcn foundation, logo, or favicon.
- Do not build a marketing landing page as the product shell. The first
  authenticated screen should be a usable operational dashboard/home.
- Do not create separate nav constants, shell layouts, fetch clients, error
  classes, DTOs, validation tables, status enums, or workflow state machines per
  surface.
- Do not treat Risk Register's first module shell as the final all-platform IA.
- Do not collapse participant mode and organizer mode into one role list, or use
  role names as user-facing modes.
- Do not use the terms `range`, `event`, `scenario`, `challenge`, `asset`,
  `credential`, `risk`, `mitigation`, or `audit` interchangeably. UX copy should
  preserve the taxonomy unless the maintained IA is updated.
- Do not make client-side route guards, hidden links, or disabled buttons the
  security boundary.
- Do not call legacy Django form/action URLs or app-local JSON endpoints from
  SPA data code.
- Do not render user-entered risk text, challenge text, scenario YAML,
  comments, audit JSON, provider messages, or upload metadata as HTML/Markdown
  unless a sanitizer policy is explicitly accepted.
- Do not store drafts, tokens, signed URLs, credentials, challenge flags, or
  provider payloads in localStorage/sessionStorage to preserve flow state.
- Do not auto-retry unsafe mutations or long-running destructive actions.
- Do not weaken ADR guard, import-linter, Django i18n, collectstatic,
  Stylelint, ESLint, Vitest, Playwright, or legacy Jest checks to land design or
  SPA work.

## Non-Goals

- No implementation of SPA routes, app shell code, nav registry, APIs, backend
  serializers, migrations, services, components, tests, feature flags, or route
  cutovers in this preflight.
- No retirement of Django template routes; each surface needs its own
  implementation issue and route-retirement decision.
- No replacement of Django sessions, OIDC, Identity Platform, CTF magic links,
  CSRF, API-token auth, DRF permissions, or provider login/logout flows.
- No new runtime secret delivery, cloud infrastructure, Terraform, Kubernetes,
  workers, websocket auth scheme, or second origin/server.
- No replacement of existing domain services, repositories, schemas,
  validation, exception handling, audit stores, logging format, or persistence
  policy.
- No inclusion of MkDocs documentation-site redesign or the static privacy
  notice; both are out of scope for #1368.
