# SPA Mission Control Workspace Preflight (#1370)

Status: pre-implementation guidance

Date: 2026-07-10

Issue: GitHub #1370, "SPA Phase 2: Mission Control workspace"

Requirement: none. The GitHub issue title, body, constraints, and acceptance
criteria are the shipping contract.

This note sets repo-wide architecture guardrails for moving Mission Control into
the platform SPA. It is not an implementation plan and does not implement
routes, components, APIs, serializers, services, tests, or legacy-route
retirement.

## Scope Boundary

#1370 must build on the accepted SPA and shell work:

- ADR-013: one shared, role-aware platform IA and navigation contract.
- ADR-029: React 18, TypeScript, Vite, React Router v7, TanStack Query v5, one
  Django origin, canonical `/api/v1/`, session plus CSRF for browser calls, and
  no browser-held `shf_` API tokens.
- `docs/design/spa-cohesive-ux-1368.md`: the Mission Control use cases, layout
  patterns, state requirements, and domain-status-to-intent mapping.
- `docs/architecture/spa-platform-shell-preflight-1369.md`: shared shell,
  navigation metadata, bootstrap, route ownership, and rollout flag patterns.
- The existing Mission Control `/api/v1/mission-control/` surface, CMS service
  facades, Channels consumers, and Guacamole bootstrap flow.

No new ADR is required if #1370 stays within ADR-013 and ADR-029. Update ADR
docs only if implementation changes an enforceable guardrail: frontend stack,
auth posture, API boundary, route-retirement policy, static asset policy,
navigation source of truth, import/layer rules, CI gates, or documented range
lifecycle and event-delivery semantics.

## Architecture Decisions And Guardrails

- The SPA owns presentation, route state, user interaction, loading/error/empty
  states, accessibility, and client orchestration. It does not own range
  authorization, lifecycle policy, scenario launchability, Guacamole token
  exchange, terminal admission, durable state, audit policy, or persistence.
- All Mission Control data access uses canonical DRF routes under
  `/api/v1/mission-control/`. Do not call legacy `/mission-control/...` JSON or
  form-action routes from SPA data code and do not add ad hoc JSON endpoints.
- Reuse the existing typed SPA client, generated OpenAPI types, React Router,
  TanStack Query, shared shell, shared nav metadata, shadcn/ui primitives, and
  design-system state mappings. Do not create a Mission Control fetch wrapper,
  store, router, DTO package, error class, badge system, dialog system, or local
  status vocabulary.
- Preserve service boundaries. Range launch and lifecycle mutations route
  through `mission_control.api.ranges` into `cms.services` and the engine
  facades. The frontend may display progress and disable controls, but CMS and
  engine services remain the source of truth.
- Preserve identifier meaning. Newer range flows are request-id centered:
  `RangeInstance.request.request_id` is the durable correlation key; the legacy
  integer `RangeInstance.range_id` is nullable and must not be treated as the
  engine or UI primary id. Instance UUIDs identify terminal and Guacamole
  targets. `RangeSource` is server-derived only and never user supplied.
- Preserve range provenance. Mission Control and CTF ranges are distinct
  product paths via `shared.enums.RangeSource`; do not collapse active-range
  admission, participant range views, or cleanup into one user-wide range slot.
- Preserve rollout and rollback. Mission Control SPA route ownership must be
  guarded by a non-secret, per-surface server flag (for example a
  Mission-Control-specific extension of the existing SPA flag pattern), read per
  request and surfaced through bootstrap. Legacy Django routes stay available
  until a later route-retirement issue explicitly removes them.
- Treat websockets as live projection, not authority. Range-status and terminal
  sockets hydrate and stream state, but correctness still comes from PostgreSQL,
  CMS services, the transactional event/outbox/reconciler path, and explicit
  `/api/v1/` reads. Advisory websocket loss must not strand the UI in a false
  state.
- Guacamole stays server-brokered. The SPA queues a bootstrap request, follows
  status/open responses, and embeds or opens the resulting session as a
  short-lived browser action. It must not generate Guacamole JSON auth payloads,
  hold Guacamole shared secrets, or persist signed session URLs.
- Terminal access stays on the existing Channels route and server-side
  admission. The SPA may host the xterm/Guacamole workspace, reconnect affordance,
  and status copy, but `SSHConsumer`, `terminal_sessions`, and `engine.services`
  keep ownership, range-state, capacity, timeout, and secret resolution checks.
- Preserve audit and observability. Lifecycle audit stays in
  `_audit_range_lifecycle` and `cms.services.audit_log`; terminal-session audit
  stays in the existing websocket consumer path. Client diagnostics should carry
  action names and request ids only, never terminal data, credentials, signed
  URLs, scenario YAML, or provider payloads.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1370 |
| --- | --- | --- |
| SPA architecture | ADR-029; `docs/architecture/spa-cutover-architecture-1300.md`; `frontend/src/api/client.ts`; `frontend/src/api/queryClient.ts`; `frontend/src/router.tsx` | One router, one query client, one typed fetch client, generated API types, `/api/v1/` only. |
| Shell and IA | ADR-013; `frontend/src/app/nav.ts`; `frontend/src/components/app-shell.tsx`; `docs/design/spa-cohesive-ux-1368.md` | Register Mission Control surfaces in the shared navigation/route-ownership contract; do not fork a module shell. |
| Rollout | `shared/spa_host.py`; `shared/api/bootstrap.py`; Risk Register and platform SPA flags | Add/use a non-secret per-surface flag and legacy fallback; do not use Vite env variables for deployment state. |
| Range API | `mission_control/api/ranges.py`; `mission_control/api/_base.py`; `mission_control/api/serializers.py`; `mission_control/api/permissions.py` | Reuse serializer validation, scope permissions, participant lifecycle block, legacy/canonical error split, and actor resolution. |
| Range services | `cms.services.create_range`; `get_active_range`; `get_range_by_request_id`; `destroy/cancel/pause/resume` variants | Keep lifecycle, ownership masking, status transitions, engine dispatch, and audit in services. |
| Status vocabulary | `shared.enums.ResourceStatus`; `cms.models.RangeInstance`; `cms.models.lifecycle.apply_terminal_soft_delete` | Map statuses to UI intents; do not define a frontend state machine or client-only terminal/deleted semantics. |
| Provenance and ids | `shared.enums.RangeSource`; `RangeInstance.request_id`; instance UUIDs | Do not conflate CTF and Mission Control ranges, request ids and legacy range ids, or range ids and instance ids. |
| Guacamole | `mission_control/api/guacamole.py`; `mission_control/guacamole.py`; `mission_control/guacamole_bootstrap.py`; `GuacamoleBootstrapRequest` | Server owns token exchange, retry, parking, expiry, and one-time URL consumption. |
| Terminals and live state | `mission_control/routing.py`; `SSHConsumer`; `RangeStatusConsumer`; `NGFWStatusConsumer`; `config/asgi.py`; `shared.channels.groups` | Use existing session-authenticated Channels routes and close codes; no second websocket auth scheme. |
| Auth and scopes | `shared/api_tokens.authentication`; `shared/api_tokens.scopes`; `shared/api_tokens.permissions`; `shared.auth` | Browser sends no bearer token; programmatic tokens remain scoped by Mission Control subsurface. |
| Errors and logging | `shared/api/errors.py`; `shared.errors.classify_user_message`; `config.middleware.RequestIDMiddleware`; `shared.log_sanitize` | Show safe envelope messages and request ids; keep raw exceptions and sensitive values out of UI/logs. |
| Design/accessibility | `frontend/src/components/ui/*`; `frontend/src/app/state-map.ts`; `docs/design/spa-design-system-foundation-1299.md` | Reuse shadcn/ui primitives, shared status mapping, focus, dialog, table, tab, skeleton, alert, and AA patterns. |
| Architecture gates | `.importlinter`; `scripts/check_layer_imports/layer_imports.yaml`; `scripts/adr_guard/adr_guard.py`; `.github/workflows/_quality.yml` | Keep Python layer rules, SPA build/typecheck/lint/test/e2e, ADR guard, and import checks intact. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: authenticated SPA page routes start after a Django session
  exists. Unsafe HTTP calls use same-origin cookies plus `X-CSRFToken` from the
  shared SPA client. Login/logout remain provider and Django flows.
- API-token surface: `ApiTokenAuthentication` stays first and fail-closed. Bad
  bearer tokens never fall through to a session. SPA browser code never stores
  or sends `shf_` tokens; programmatic callers keep explicit Mission Control
  scopes.
- Authorization and ownership surface: `HasMissionControlActor`,
  `require_scope`, `block_participant_lifecycle_permission`,
  `is_ctf_participant_only`, CMS ownership checks, engine terminal checks, and
  Guacamole target resolution remain authoritative. Hidden buttons, nav
  visibility, feature flags, and route gates are advisory only.
- Secret-handling surface: session cookies, CSRF tokens, API tokens, Guacamole
  shared secrets, signed Guacamole URLs, SSH/RDP credentials, private keys,
  presigned upload/download URLs, scenario payloads, terminal I/O, provider
  payloads, challenge flags, private hostnames, and cloud identifiers must not
  enter static bundles, localStorage/sessionStorage, URL query strings, logs,
  schema examples, test snapshots, screenshots, GitHub summaries, or process
  argv.
- Config/env surface: rollout flags are non-secret Django settings documented
  through the existing config/env manifest path if a new binding is added.
  Build-time Vite variables must not carry deployment state, secrets, hostnames,
  tokens, or tenant data.
- Static asset surface: Vite output is public, cacheable, and served by Django
  staticfiles/WhiteNoise. It contains UI code and non-secret constants only.
- Payload/schema validation surface: DRF serializers validate launch,
  lifecycle, upload, Guacamole, NGFW, and credential shapes; CMS scenario,
  credential, upload, and range schemas keep deeper domain validation. Client
  pre-checks may improve responsiveness but cannot replace serializer/service
  checks.
- Error-envelope surface: canonical `/api/v1/` errors use
  `{"error": {"code", "message", "details?", "request_id?"}}`. The UI may show
  safe messages and request ids, but not raw exception text, stack traces, SQL
  or provider errors, cookies, tokens, signed URLs, terminal output, or raw
  audit JSON.
- Logging/observability surface: `X-Request-ID` flows through the shared client
  and `RequestIDMiddleware`; server logs use ECS formatting and redaction
  helpers. Range lifecycle, Guacamole, and terminal logs should reference safe
  ids and sanitized values only.
- WebSocket/special-transport surface: terminal, range-status, and NGFW-status
  sockets use `AllowedHostsOriginValidator` and `AuthMiddlewareStack` in
  `config/asgi.py`. No CORS, second origin, websocket bearer-token channel, or
  client-generated secret handshake is introduced.
- Persistence/audit surface: PostgreSQL remains authoritative for requests,
  ranges, instances, Guacamole bootstrap rows, audit rows, and outbox/reconciler
  recovery. Browser state and query cache are disposable projections.
- Import/layer surface: frontend code stays outside the Python import graph.
  Backend changes respect ADR-001 and existing `.importlinter` contracts: use
  `shared` contracts and public service facades, not cross-app private imports
  or direct `cyberscript` imports outside `shared`.
- OS/runtime exposure surface: #1370 should not introduce shell commands,
  Terraform, Kubernetes, cloud CLIs, background workers, temp files, or runtime
  secret delivery. Build/test/e2e commands must not pass cookies, tokens,
  signed URLs, credentials, or terminal data through argv or emitted artifacts.
- Accessibility/i18n surface: Mission Control list/detail/workspace/editor and
  destructive-confirmation patterns must meet WCAG 2.1 AA. SPA strings need the
  repository's chosen extraction/translation path before broad cutover.

## Extensibility Seams

- Route-ownership seam: prefix, rollout flag, legacy fallback, nav metadata,
  and client route definition should be parameterized so later Mission Control
  subareas, CTF, Scenario Editor, and Admin can move without copying host logic.
- Range-read seam: a typed Mission Control range query should be parameterized
  by `request_id`, legacy `range_id` only where an existing API requires it,
  source/provenance where server-owned, and view context such as list, detail,
  or active range. Future range history or multi-range views should extend this
  shape, not add a second client.
- Status seam: one mapping turns `ResourceStatus` and Guacamole/bootstrap/socket
  statuses into design-system intents, accessible labels, destructive-action
  availability, and progress copy. New status values add mappings and tests,
  not new components or client state machines.
- Transport seam: live state should prefer Channels when available and fall
  back to bounded, cancel-on-unmount polling of canonical `/api/v1/` reads.
  Retry policy remains idempotent-GET only; unsafe lifecycle actions are never
  auto-retried.
- Access seam: terminal and Guacamole target selection is parameterized by
  instance UUID and protocol (`rdp`, range `ssh`, NGFW `ssh`) while keeping URL
  issuance server-side. Future protocols should extend the server broker and
  generated API types, not construct URLs in React.
- Asset seam: agents, NGFW, credentials, and uploads should use shared list,
  detail, form, upload, and destructive-confirmation primitives. Future asset
  kinds add metadata and API types, not new local workflow engines.

## Whole-Repo Scope

#1370 implementation should evaluate these surfaces together:

- Architecture/design: ADR-013, ADR-016, ADR-022, ADR-029,
  `docs/design/spa-cohesive-ux-1368.md`,
  `docs/design/ux-003-information-architecture-sitemap.md`,
  `docs/architecture/spa-cutover-architecture-1300.md`,
  `docs/architecture/spa-platform-shell-preflight-1369.md`, and this note.
- Frontend: `shifter/shifter_platform/frontend/package.json`,
  `vite.config.ts`, `src/router.tsx`, `src/api/*`, `src/app/*`,
  `src/components/*`, `src/features/risk-register/*`, and any new Mission
  Control feature folder.
- Django shell/config: `config/urls.py`, `config/api_urls.py`,
  `config/settings.py`, `config/env-manifest.json`, `config/_drf_settings.py`,
  `config/asgi.py`, `config/middleware.py`, `shared/spa.py`, and
  `shared/spa_host.py`.
- Mission Control: `mission_control/api/*`, `mission_control/views/*`,
  `mission_control/urls.py`, `mission_control/routing.py`,
  `mission_control/consumers.py`, `mission_control/status_consumers.py`,
  `mission_control/terminal_sessions.py`, `mission_control/terminal_executor.py`,
  `mission_control/guacamole.py`, `mission_control/guacamole_bootstrap.py`,
  and `mission_control/models.py`.
- Cross-app services/contracts: `cms/services/*`, `cms/models/RangeInstance`,
  `ctf/services/range/*`, `engine/services/*`, `shared/enums.py`,
  `shared/schemas/*`, `shared/api/*`, `shared/api_tokens/*`,
  `shared/auth.py`, `shared/channels/*`, `shared/errors.py`, and
  `shared/log_sanitize.py`.
- Legacy compatibility: `templates/mission_control/**`,
  `templates/ctf/participant/range.html`, `static/css/**`, and `static/js/**`
  only as parity/rollback evidence, not SPA data dependencies.
- Enforcement/workflows if touched: `.github/workflows/**`, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/adr_guard.py`, frontend ESLint/Vitest/Playwright config,
  root/frontend package scripts, and documentation coverage manifests.

## Gotchas And Anti-Patterns

- Do not redesign the locked Apple-dark Tailwind v4 plus shadcn/ui theme, logo,
  favicon, typography, or color language.
- Do not implement a Mission Control-only shell, navigation schema, route guard,
  fetch client, error envelope, DTO set, status enum, validation layer,
  exception hierarchy, or workflow state machine.
- Do not deepen presentation-layer coupling to engine, cloud, Guacamole,
  Secrets Manager, SSH, Terraform, or Kubernetes. Presentation talks to
  canonical DRF and websocket boundaries.
- Do not conflate `request_id`, legacy integer `range_id`, `RangeInstance.pk`,
  engine range id, instance UUID, Guacamole bootstrap request id, NGFW `app_id`,
  or CTF participant id.
- Do not make `RangeSource` user controlled or collapse CTF and Mission Control
  active-range admission into one frontend assumption.
- Do not treat websocket delivery as correctness or recovery. Lost/stale socket
  events must reconcile through canonical reads and existing server recovery.
- Do not expose or persist Guacamole URLs beyond their one-time/short-lived
  use, and do not render signed URLs into logs, screenshots, snapshots, or
  browser storage.
- Do not auto-retry launch, destroy, cancel, pause, resume, credential, upload,
  or NGFW mutations. Surface failure and require explicit user action.
- Do not render terminal output, scenario YAML, provider payloads, audit JSON,
  credential values, or upload metadata as HTML/Markdown without an accepted
  sanitizer policy.
- Do not remove legacy Django routes, templates, or POST handlers in #1370.
  Route retirement remains a later explicitly authorized issue.
- Do not weaken ADR guard, import-linter, Django tests, SPA build/typecheck,
  ESLint, Vitest/axe, Playwright, collectstatic, or deployment checks.

## Non-Goals

- No implementation of SPA pages, components, routes, API wrappers, serializers,
  migrations, services, tests, flags, or route cutover in this preflight.
- No removal or retirement of legacy Mission Control Django routes/templates.
- No replacement of Django sessions, OIDC/Identity Platform/Cognito flows, CTF
  magic links, CSRF, platform API-token auth, Mission Control scopes, DRF
  permissions, or provider logout behavior.
- No new range lifecycle engine, orchestration path, persistence model, event
  bus, websocket auth scheme, Guacamole auth mechanism, terminal executor, or
  credential delivery mechanism.
- No new cloud infrastructure, Terraform, Kubernetes, background worker,
  runtime secret delivery, SSR server, second origin, or CORS posture.
- No Mission Control-specific visual language or component library.
