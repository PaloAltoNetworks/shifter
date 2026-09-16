# SPA Cutover: Frontend Architecture and Guardrails

Date: 2026-07-04

Issue: [#1300](https://github.com/Brad-Edwards/shifter/issues/1300) (SPA
cutover: high-level frontend architecture and guardrails)

Milestone: SPA Cutover

Status: Accepted. The binding decisions in this document are recorded as
**ADR-029** in [`docs/adr/index.yaml`](../adr/index.yaml) (landed in the same
change). ADR-029 is the enforcement control-plane record; this document is the
detailed design it references as evidence. There is one source of truth: the
rules live in the registry, the reasoning and detail live here.

Companion: [`docs/design/spa-design-system-foundation-1299.md`](../design/spa-design-system-foundation-1299.md)
(stack-neutral design system; this document makes the stack choice it deferred)

## Purpose

This document defines the target frontend architecture for migrating the
Shifter portal from server-rendered Django templates to a single-page
application, and the guardrails that keep the migration from forking auth,
routing, the API envelope, or the service boundaries. It is a decision record
and a plan, not an implementation. Per-module cutovers are later issues that
must conform to what is decided here.

The backend is healthy and is not in scope to change wholesale. The portal
already exposes a versioned DRF surface at `/api/v1/` with `NamespaceVersioning`
(`config/api_urls.py`), a standardized error envelope
(`shared/api/errors.py`), `PageNumberPagination` at `PAGE_SIZE = 50`
(`config/_drf_settings.py`), and a fail-closed API-token plus session auth
stack (`shared/api_tokens/authentication.py`). The SPA consumes that surface;
it does not replace it and does not add a parallel one.

## Open decisions for sign-off

These are the substantive choices this document commits to. They are called out
here so they can be confirmed or changed at review rather than discovered later.

1. **Stack: React 18 + TypeScript + Vite.** Confirmed direction.
2. **Deployment: build the bundle at container-image build time**, emit hashed
   assets into Django's static tree, serve via the existing WhiteNoise manifest
   storage. No committed build output. (Section "Build and deploy integration.")
3. **Route ownership: one SPA host, progressive path takeover.** A single
   Django view serves the SPA shell for SPA-owned path prefixes; unmigrated
   modules keep their existing Django template routes untouched. (Section
   "App shell, routing, and legacy compatibility.")
4. **Browser auth stays session-cookie + CSRF header.** API tokens remain for
   programmatic clients only and are never put in the browser. (Section
   "Auth, session, CSRF.")
5. **Bootstrap endpoint is a new backend gap.** The SPA needs a JSON
   `/api/v1/` session/bootstrap endpoint to replace today's Django context
   processors. (Sections "Authenticated bootstrap state" and "Backend API
   gaps".)
6. **Migration order: Mission Control, then CTF, then Scenario Editor, then
   Docs.** Ordered by DRF maturity and blast radius. The retired feature is not
   a migration target. (Section "Module migration order.")

## Frontend stack choice

**React 18 with TypeScript, built by Vite.** Rationale, given the concrete
constraints of this repo:

- The repo has **no existing bundler, no TypeScript, and no SPA build step**;
  the only frontend toolchain today is ESLint, Stylelint, and Jest over
  hand-authored vanilla ES modules (`.github/workflows/_quality.yml`;
  `shifter_platform/package.json`). Any SPA framework is a greenfield addition,
  so ecosystem depth and testing maturity matter more than incremental fit.
- The design system (#1299) is framework-neutral plain CSS custom properties
  (`docs/design/design-system/tokens.css`, `components.css`). It attaches to
  React with no adapter: components consume semantic role tokens via ordinary
  `className`. No CSS-in-JS is introduced; the token layer stays the single
  source of truth.
- React plus Playwright plus Testing Library is the best-supported combination
  for the accessibility and user-flow coverage the design system and this
  migration require.
- The backend boundary (session + CSRF, DRF `/api/v1/`) favors a pure
  client-rendered SPA over a Node SSR meta-framework. An SSR framework would
  introduce a second server, a second auth surface, and a second place for CSRF
  and session handling to drift. A client-only SPA served as static assets by
  Django keeps exactly one origin, one session, one CSRF posture.

TypeScript is required, not optional: the `/api/v1/` envelope, pagination
shape, and per-resource schemas are worth encoding as types generated from the
existing drf-spectacular schema (`/api/v1/schema/`).

State and data-fetching libraries (for example a query cache and a router) are
implementation choices for the first module issue; this document fixes only the
framework, language, and bundler, plus the client conventions in the
"API client conventions" section that any chosen data layer must honor.

## Build and deploy integration

The SPA is a static asset bundle owned by Django's static pipeline. It is not a
separately deployed service.

- **Source location:** a dedicated frontend workspace inside the portal
  package (proposed `shifter/shifter_platform/frontend/`) holding the Vite
  project, `tsconfig.json`, and TS sources. It is a sibling of the Django app
  packages, outside the Python import graph.
- **Build:** `npm ci && npm run build` (Vite) runs during Docker image build,
  before `collectstatic`. Vite emits content-hashed JS and CSS into a build
  output directory that is added to `STATICFILES_DIRS` (or emitted directly
  under `static/spa/`). `collectstatic` then folds the bundle into
  `STATIC_ROOT`, and the existing `CompressedManifestStaticFilesStorage`
  (WhiteNoise) fingerprints and compresses it (`config/settings.py`).
- **Serving:** WhiteNoise serves the hashed assets in production exactly as it
  serves current static files. No CDN change is required. The SPA host template
  references the built entry via a manifest lookup so hashed filenames resolve.
- **No committed build artifacts.** The build output is gitignored; CI builds it
  from source. This keeps the diff reviewable and avoids stale bundles.
- **Dev workflow:** the Vite dev server runs locally with HMR and proxies
  `/api/v1/` (and `/ws/`) to the Django/Daphne backend, so cookies and CSRF
  behave as same-origin during development. Production has a single origin, so
  no CORS is introduced in either environment.

## App shell, routing, and legacy compatibility

The migration is path-by-path, never big-bang. Django and the SPA coexist on
one origin; the compatibility contract is that **no legacy route is removed
until a module-specific issue retires it** (issue constraint).

- **SPA host view.** A single Django view renders one minimal HTML shell (the
  SPA mount point plus the built entry script and the design-system CSS). It is
  registered for the path prefixes the SPA owns. It carries `@ensure_csrf_cookie`
  so the CSRF cookie is present before the first API call.
- **Progressive path takeover.** Each migrated module hands its top-level path
  prefix to the SPA host (client-side routing owns sub-paths under it) while
  unmigrated modules keep their current Django `urls.py` untouched. Because
  ownership is per-prefix, a half-migrated portal is always in a valid state:
  some prefixes render the SPA shell, the rest render Django templates.
- **Navigation.** The SPA renders its own app shell and navigation for
  SPA-owned modules, replacing the five near-duplicate Django `base.html`
  shells within its scope. Cross-links to still-Django modules are ordinary
  anchors (full page loads) until those modules migrate. This is expected and
  acceptable during migration.
- **Client routing.** The SPA uses history-API routing. The Django SPA host is
  configured so unknown sub-paths under an SPA-owned prefix return the shell
  (client router resolves them), while paths outside SPA-owned prefixes fall
  through to Django. Deep links and refresh work in both worlds.

### Authenticated bootstrap state

Today the shell state the SPA needs is injected by Django context processors:
current user and permissions (`shared.context_processors.user_permissions`),
active range (`mission_control.context_processors.active_range`), and CTF
navigation (`ctf.context_processors.ctf_navigation`). A client-rendered SPA
cannot read context processors.

The SPA loads this state once, after auth, from a **new JSON bootstrap
endpoint** on `/api/v1/` returning the authenticated principal, effective
permissions, feature flags, and active-range summary. This is a backend gap
(see "Backend API gaps"). Feature flags load as part of this same bootstrap
payload; the SPA does not fetch flags from a second channel.

## Auth, session, CSRF

The browser auth posture does not change and is not weakened.

- **Session cookie is the browser credential.** DRF already lists
  `SessionAuthentication` after `ApiTokenAuthentication`
  (`config/_drf_settings.py`); browser requests with no bearer token fall
  through to session auth (`shared/api_tokens/authentication.py` returns `None`
  when no bearer is present). The SPA relies on the session cookie and sends no
  `Authorization` header.
- **API tokens stay out of the browser.** `shf_` bearer tokens
  (`shared/api_tokens/models.py`) are for programmatic and CLI clients. The SPA
  never stores or sends one. This preserves the fail-closed token path and
  avoids putting long-lived credentials in JS.
- **CSRF via header, no exemptions.** For unsafe methods the SPA reads the CSRF
  token from the `csrftoken` cookie and sends it as the `X-CSRFToken` header,
  which `CsrfViewMiddleware` accepts. `CSRF_TRUSTED_ORIGINS` already comes from
  env (`config/settings.py`). **No `csrf_exempt` is added** (there are none in
  portal production code today, and none will be introduced), honoring the issue
  constraint directly.
- **Login.** `platform_login` already carries `@ensure_csrf_cookie` and renders
  the identity-platform login. Provider flows (Identity Platform / Firebase,
  OIDC / Cognito, dev-login, CTF magic-link) remain server-driven; the SPA
  begins after an authenticated session exists. Unauthenticated API calls
  return 401/403 in the envelope, and the SPA redirects to the Django login URL.
- **Logout.** `logout_view` is `@require_POST` and branches per backend (Cognito
  redirect, Identity Platform template, or `LOGOUT_REDIRECT_URL`). The SPA
  performs a POST with the CSRF header and then follows the returned redirect.
  Making logout return a JSON `redirect_url` uniformly (as
  `identity_platform_session` already does for login) is a small backend
  smoothing item, noted as a gap.

## API client conventions

All portal data access goes through `/api/v1/`. The SPA must not add ad hoc
JSON routes or call legacy per-app `/mission-control/api/...` or `/ctf/api/...`
endpoints (issue constraint). A single typed API client enforces the following.

- **Error envelope.** Every non-2xx response is parsed as
  `{"error": {"code", "message", "details?", "request_id?"}}`
  (`shared/api/errors.py`). The client raises a typed error carrying those
  fields; UI surfaces `message`, maps `details` to form-field errors, and logs
  `request_id` for correlation.
- **Request correlation.** The client propagates `X-Request-ID` so client logs
  and server logs join (the backend already reads `request.request_id`).
- **Pagination.** Lists use `PageNumberPagination` (`page` query param,
  `PAGE_SIZE = 50`). The client exposes typed paged results; infinite-scroll or
  pager UI is built on the standard `count`/`next`/`previous` shape.
- **Validation.** Backend validation is authoritative. The SPA may do
  presentational pre-checks (required, format) for responsiveness but must not
  duplicate or replace backend rules (issue constraint). Field errors always
  come from the `details` map on a 400.
- **Retries.** Automatic retry is limited to idempotent GETs on network/5xx
  with bounded exponential backoff. Unsafe methods are never auto-retried;
  they surface the error for explicit user action.
- **Polling.** Where a websocket channel exists (range status, terminal), the
  SPA prefers it. Where it does not, long-running state is polled at a bounded
  interval with backoff, cancelled on unmount.
- **Types.** Request/response types are generated from the drf-spectacular
  schema (`/api/v1/schema/`) so the client stays in lockstep with the backend
  contract.

## Special flows

These flows already have backend implementations; the SPA wraps them, it does
not reinvent them.

- **Guacamole console / opener.** DRF views exist
  (`mission_control/api/guacamole.py`: RDP/SSH URL views, bootstrap
  status/open). The SPA calls the bootstrap-status endpoint, polls or listens
  until ready, then opens the console URL. Token exchange and retry stay
  server-side (`mission_control/guacamole.py`).
- **WebSockets.** Channels routes exist for `ws/terminal/<uuid>/`,
  `ws/range-status/<uuid>/`, `ws/ngfw-status/<uuid>/`
  (`mission_control/routing.py`), authenticated through
  `AuthMiddlewareStack` over the same session (`config/asgi.py`). The SPA
  connects with the session cookie; no separate WS auth is introduced. The
  terminal uses the existing xterm assets. The disabled shared-notifications
  consumer (`WEBSOCKET_NOTIFICATIONS_ENABLED`) stays out of scope.
- **Presigned uploads.** The initiate/complete/cancel DRF views
  (`mission_control/api/uploads.py`; CTF and CMS have their own) return
  presigned targets; the SPA uploads directly to the presigned URL, then calls
  complete. Upload limits/expiry stay server-enforced.
- **File downloads.** Downloads resolve to presigned URLs (for example
  `/api/v1/ctf/files/<uuid>/download/`); the SPA navigates to or fetches the
  presigned target. No file bytes proxy through the SPA.
- **Long-running range lifecycle.** Launch/cancel/destroy/pause/resume are DRF
  actions (`mission_control/api/ranges.py`); the SPA issues the action, then
  tracks progress over `ws/range-status/` (websocket preferred, bounded polling
  fallback). Orchestration stays in the `engine` app and `cms.services` seam.

## Module migration order

Ordered by DRF maturity (least backend work first) and blast radius.

1. **Mission Control.** Class-based DRF views for ranges, agents, scenarios,
   uploads, Guacamole, NGFW, credentials (`mission_control/api/`). Exercises the
   hardest flows (websockets, Guacamole, uploads, long-running lifecycle).
2. **CTF.** Large DRF surface but currently legacy-wrapped without serializers
   (`ctf/api/`, ~50 endpoints via `legacy_api_view`). Needs proper serializers
   for a clean typed client; big blast radius (participant plus admin).
3. **Scenario Editor (CMS).** Only two DRF views exist today
   (`cms/api/urls.py`: YAML validate/create). Needs the most new backend API
   (list/detail/edit/clone/toggle/export as DRF) before its SPA cutover.
4. **Docs.** No `/api/v1` API and none needed. Decide at its turn whether docs
   stay server-rendered (simplest) or become a build-time static content route
   in the SPA. Lowest priority.

### Criteria to retire a Django template route

A legacy Django template route may be retired only when all hold for its module:

- The SPA screen reaches feature parity with the Django screen.
- All data access uses `/api/v1/` (no legacy per-app JSON endpoint remains in
  the SPA path).
- Accessibility parity is met (design-system AA baseline; keyboard and screen
  reader paths verified).
- Unit, integration, and Playwright user-flow coverage exist and pass.
- Auth, CSRF, websocket, and file flows for that module are verified end to end.
- A module-specific issue explicitly authorizes retirement (routes are not
  removed implicitly).

## Backend API gaps

Required before or during the modules that depend on them:

- **Session/bootstrap endpoint** (`/api/v1/`): current principal, effective
  permissions, feature flags, active-range summary. Replaces the Django context
  processors. Needed by the first SPA module.
- **CSRF cookie priming** outside the SPA host view if any SPA entry path does
  not pass through it (the `@ensure_csrf_cookie` host view is the default
  mechanism).
- **Uniform JSON logout** returning `redirect_url` for all backends (parity with
  the login session endpoint).
- **CMS scenario-editor DRF CRUD**: list, detail, edit, clone, toggle-enabled,
  toggle-staff-only, export as DRF views/serializers (only YAML validate/create
  exist today).
- **CTF serializers**: promote the legacy-wrapped endpoints to serializer-backed
  DRF for a typed client.
- **Feature-flag source of truth**: keep flags in the typed bootstrap contract.

## No-go criteria for full cutover

Do not retire the last Django routes or declare the portal SPA-complete while
any of these hold:

- Any migrated module lacks accessibility parity or Playwright user-flow
  coverage.
- Any backend gap above is unfilled for a migrated module.
- Any auth provider path (Identity Platform, OIDC/Cognito, dev-login, CTF
  magic-link) does not complete cleanly into the SPA.
- Any special flow (websocket terminal, range status, Guacamole, presigned
  upload, download, range lifecycle) is unverified in the SPA.
- The Docs route strategy is undecided.
- CI does not yet run the SPA build, typecheck, lint, unit, and Playwright jobs
  as required gates.

## Testing strategy

- **Unit / component:** Vitest plus React Testing Library for SPA code
  (replacing Jest for new code). The existing Jest suite over `static/js/`
  stays until the legacy vanilla-JS assets it covers are retired.
- **Integration:** the typed API client tested against the drf-spectacular
  schema and mocked envelope responses, so envelope, pagination, and error
  mapping are covered without a live backend.
- **Accessibility:** automated axe checks in component and e2e tests, enforcing
  the design-system AA baseline; keyboard and focus-order assertions on
  interactive components.
- **User flows:** Playwright against a running Django + SPA stack for the
  per-module critical paths (login, the module's core CRUD, and its special
  flows).
- **Existing Django checks:** unchanged. Python tests, DRF tests, `adr_guard`,
  import-linter, ruff, mypy, and the current ESLint/Stylelint jobs continue to
  run; the SPA jobs are added alongside, not in place of them.

## ADR and guardrail updates required

A new frontend introduces guardrail surface the repo does not model today (the
import-linter graph and ADR checks are Python-only). Landing the stack requires:

- **ADR-029 (landed with this document)** records the frontend stack decision
  (React + TS + Vite), the static-asset deployment model, the no-SSR /
  single-origin posture, and the `/api/v1`-only frontend boundary as three
  enforceable rules in `docs/adr/index.yaml`. It is `agent-policy` enforced now;
  the automated boundary check below promotes ADR-029-R2 to a coded check when
  the first SPA module lands.
- **Frontend boundary guardrail**: an enforced rule that SPA code calls only
  `/api/v1/` (no legacy per-app JSON routes, no ad hoc endpoints), analogous in
  spirit to the Python layer contracts in `.importlinter`. Mechanism to be
  defined with the ADR (lint rule or check script).
- **Generated-assets policy**: build output is gitignored and built in CI;
  document this so `adr_guard` and reviewers do not expect committed bundles.
- **CI check additions** (required before SPA implementation PRs land):
  - Node build job: `npm ci && npm run build` (Vite) in
    `.github/workflows/_quality.yml`.
  - Typecheck: `tsc --noEmit`.
  - Lint: ESLint over the TS sources (extend the current ESLint job or add a
    TS-aware config; keep the `static/js/` job until legacy JS is gone).
  - Unit: Vitest with a coverage gate.
  - E2E: Playwright job against a built stack.
  - Accessibility: axe assertions within the Vitest/Playwright jobs.
  - Dockerfile/entrypoint: add the Vite build before `collectstatic`.
- **Guardrail-file registration**: any new guardrail/config files
  (frontend lint config, CI job, ADR) are added to the guardrail-file list and
  ADR enforcement docs per the repo's guardrail discipline
  (`.gc/plan-rules.md`), and `scripts/adr_guard` is updated if a new check is
  introduced.
- **Documentation coverage**: register the SPA as a platform feature in
  `docs/adr/documentation-coverage.yaml` with a user doc and a technical doc
  when the first module ships.

## Platform shell mount and route ownership (#1369)

The platform shell (#1369) provides one router and fixes the route-ownership
model that later Phase 2 modules extend. ADR-045 removes the retired feature
from this shell without changing these platform-wide rules:

- **One router, one bundle, one basename.** The single Vite bundle mounts one
  `createBrowserRouter` at basename `/`. There are no per-module routers,
  fetch clients, or error classes (ADR-013 / ADR-029).
- **SPA host + prefix ownership.** A single host view
  (`shared.spa_host.platform_spa_host`) serves every SPA-owned page path. The
  site root is wired as an *exact* match (no global catch-all), so `/privacy/`,
  `/login/`, and other Django routes are untouched. The completed cutover has
  no runtime feature flags or server-rendered page fallback.
- **Navigation is one shared contract.** Primary nav, mode switching,
  breadcrumbs, and contextual subnav render from `frontend/src/app/nav.ts`
  (UX-003 minimum fields plus the #1368 presentation fields). Adding a surface
  adds one entry owned by the same SPA router.
  Navigation visibility is advisory UX only; endpoints remain the authority.
- **Shell state is typed bootstrap; dashboard data is a serializer-backed read.**
  Principal, advisory permission flags, and UX mode eligibility extend the
  `/api/v1/bootstrap/` serializer (`shared`-layer, no cross-app
  imports). The operational dashboard summary is a bounded cross-app read at the
  composition root (`config.api_dashboard`, `/api/v1/dashboard/summary/`),
  since `shared` may not import `cms`/`ctf` services (ADR-001).
- **Module delivery.** Mission Control, Scenario Editor, CTF, and Admin
  implementations were delivered by #1370–#1373 and completed by #1311; this issue
  delivers the shell they mount into. See
  `docs/architecture/spa-platform-shell-preflight-1369.md`.

## Constraints honored

- Canonical DRF `/api/v1/` is the only data surface; no ad hoc JSON routes.
- No CSRF exemptions for session-authenticated browser calls; CSRF via header.
- No domain behavior or duplicated validation in frontend code.
- Server-rendered page routes are retired; required form-only authentication
  posts and the canonical JSON API remain Django-owned.
- ADR and import boundaries respected; new guardrails ship with ADR updates.
