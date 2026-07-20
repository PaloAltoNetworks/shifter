# SPA CTF Workspace Preflight (#1372)

Status: pre-implementation guidance

Date: 2026-07-15

Issue: GitHub #1372, "SPA Phase 2: CTF workspace (participant + organizer)"

Requirement: none. The GitHub issue title, body, constraints, and acceptance
criteria are the shipping contract.

This note sets repo-wide architecture guardrails for moving the participant and
organizer CTF workspaces into the platform SPA. It is not an implementation
plan and does not implement routes, components, APIs, serializers, services,
persistence, rollout, or legacy-route retirement.

## Scope Boundary

#1372 must build on the accepted SPA, information architecture, and shell work:

- ADR-013: one shared, role-aware platform IA and navigation contract.
- ADR-029: React 18, TypeScript, Vite, React Router v7, TanStack Query v5, one
  Django origin, canonical `/api/v1/`, session plus CSRF for browser calls, and
  no browser-held `shf_` API tokens.
- `docs/design/spa-cohesive-ux-1368.md`: participant and organizer use cases,
  page patterns, state requirements, and terminology.
- `docs/architecture/spa-platform-shell-preflight-1369.md`: the shared shell,
  mode/navigation metadata, bootstrap, route ownership, and rollout pattern.
- `docs/architecture/ctf-drf-api-preflight-1121.md` and
  `docs/architecture/api-surface-inventory-1328.md`: the canonical CTF API
  boundary, known legacy wrappers, access semantics, and consolidation gaps.
- Existing CTF services, model validation, authorization predicates, scoring,
  range lifecycle, upload inspection, audit, and isolated-account lifecycle.

No new ADR is required if #1372 stays within ADR-013 and ADR-029. Update ADR
docs only if implementation changes an enforceable guardrail: frontend stack,
auth posture, API boundary, route-retirement policy, navigation source of
truth, static-asset policy, CTF privacy/ownership policy, import/layer rules, or
CI gates.

## Architecture Decisions And Guardrails

- The SPA owns presentation, route state, accessible interaction, disposable
  query state, and loading/empty/error/confirmation states. It does not own CTF
  eligibility, event/challenge lifecycle, release/prerequisite policy, scoring,
  flag verification, attempt limits, range lifecycle, account provisioning,
  notification delivery, audit policy, or persistence.
- All SPA data access uses `/api/v1/ctf/`. Do not call `/ctf/api/`, Django form
  actions, or scrape legacy page HTML. Where the canonical surface lacks a
  participant or organizer projection, add a serializer-owned `/api/v1/`
  contract over existing services; do not expose models directly or move
  domain logic into React.
- Publish truthful CTF request and response schemas before treating generated
  TypeScript as the client contract. CTF is currently excluded by
  `shared.api.schema.UNPUBLISHED_VIEW_MODULE_PREFIXES`, and most endpoints are
  `CTFLegacyAPIView` wrappers with only an object-shape request parser. Removing
  the exclusion without explicit serializers and response schemas would
  publish `any`-like or incomplete contracts and merely freeze legacy drift.
- Preserve role and event scope at every read and mutation. Participant mode
  and organizer mode are UX frames, not authorization. Participant access is
  an eligible, registered, non-disqualified row for the named/active event;
  organizer access is an organizer role plus ownership of the named event.
  Bootstrap/nav flags remain advisory.
- Preserve one participant-selection rule. Event- and challenge-scoped calls
  must resolve the participant with the event id; never use an unscoped first
  participant row. `active_ctf_event` is navigation context, not permission to
  another event.
- Preserve privacy projections. A participant may see their own submission and
  solve history; an organizer may see participants belonging to an event they
  own. Do not return all solve histories and filter them client-side. Preserve
  scoreboard `visible`/freeze/bracket/team semantics and explicitly choose the
  authenticated participant/organizer contract rather than accidentally using
  the public scoreboard's different access semantics.
- “Registration” means the incumbent isolated-participant-account enrollment
  lifecycle unless the issue contract is explicitly amended. Today organizers
  create/import participant seats, services attach marked temporary accounts,
  and provider/Django views handle login and required password change. The SPA
  must not invent public self-registration, accept identity claims as organizer
  authority, handle bootstrap passwords, or duplicate account/group/profile
  mutation.
- Reuse the domain exception hierarchy internally and the shared API error
  envelope at HTTP. Do not create parallel CTF API exceptions or a frontend CTF
  error class. Stable domain codes and safe field details should be mapped once
  at the DRF boundary; raw exception messages stay server-side.
- Keep mutations service-backed and concurrency-safe. Flag submission, hints,
  challenge/event CRUD, participant lifecycle, scoring, and range actions must
  retain their transactions, row locks, database constraints, state checks,
  and service-layer ownership defense. Disabled buttons are not concurrency or
  authorization controls.
- Preserve rollout and rollback with a non-secret, CTF-specific per-request
  flag combined with `PLATFORM_SPA_ENABLED`. Safe page reads may switch to the
  shared host; legacy unsafe form handlers, login/password-change/provider
  flows, and page routes remain callable for old tabs and rollback until a
  later retirement decision.
- Reuse the locked Apple-dark Tailwind v4, shadcn/ui primitives, shared shell,
  Shifter mark/favicon, and domain-status-to-intent mapping. CTF may redesign
  IA and flows within #1368, but not create a new visual language.

## Known API Readiness Gaps

These are contract gaps, not permission to create ad hoc endpoints:

- The published OpenAPI artifact intentionally omits `ctf.*`; committed
  `frontend/src/api/schema.d.ts` therefore has no CTF contract.
- Organizer event/challenge routes exist, but their bodies are manually parsed
  and responses are hand-shaped rather than explicit DRF serializers. Several
  create/update responses are intentionally narrower than their detail reads.
- Participant browse projections (active event summary, available challenge
  list, participant-safe challenge detail, progression/team context) are still
  assembled in `ctf.views.participant*` for templates. The organizer challenge
  detail shape contains organizer-only fields such as `solution` and must never
  be reused as a participant DTO.
- The canonical scoreboard route is `AllowAny` and has visibility/freeze
  semantics different from the authenticated legacy participant/organizer
  scoreboard. Treat these as distinct policies, not two URLs for one DTO.
- Participant solve-history, team join, and portions of organizer dashboard
  monitoring have no equivalent typed `/api/v1/` projection. Acceptance only
  authorizes the minimal service-backed gaps required for core workflows.
- CTF attachment upload is same-origin multipart and passes domain file
  inspection; the shared JSON-only `apiFetch` cannot be bypassed with an
  unreviewed component-local `fetch`. A shared request/upload seam must preserve
  credentials, CSRF, request ids, abort, progress, and safe error handling.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1372 |
| --- | --- | --- |
| SPA and shell | ADR-013/029; `frontend/src/router.tsx`; `frontend/src/app/nav.ts`; `frontend/src/components/app-shell.tsx` | Register CTF routes and contextual event/challenge nav in the one router and metadata model; no CTF shell or router. |
| Fetch/cache/errors | `frontend/src/api/client.ts`; `csrf.ts`; `errors.ts`; `queryClient.ts`; `shared/api/errors.py` | Same-origin session, CSRF on unsafe methods, request ids, shared envelope, bounded GET retry, no mutation retry. |
| API contract | `config/api_urls.py`; `ctf/api/*`; `shared/api/schema.py`; `config/management/commands/api_contract.py`; generated `schema.d.ts` | Add truthful serializers/schema to the canonical mount and regenerate; no hand-copied DTOs or premature un-exclusion. |
| HTTP auth/scopes | `ctf.api._base`; `shared.api_tokens.authentication`; `shared.api_tokens.scopes`; `shared.api.permissions` | Reuse actor resolution and CTF event/play scopes. Browser uses session only; token callers remain explicitly scoped. |
| Roles and ownership | `shared.auth`; `ctf.bridges.get_user_role`; `ctf.services.authorization`; `ctf.views._access`; `ctf.services.participant.queries` | Preserve organizer ownership, eligible participant status, event-scoped resolution, and no-enumeration ordering. |
| Event/challenge lifecycle | `ctf.services.event`; `ctf.services.challenge`; `ctf.enums`; CTF models' `clean()`/`full_clean()` | Services/models remain authoritative for transitions, timing, release, visibility, prerequisites, validation, and persistence. |
| Play and scoring | `ctf.services.submission`; `hint`; `scoring/*`; `assert_challenge_available_for_participant`; DB constraints | Reuse availability, attempt/cooldown, hint penalty, team/bracket/freeze, row-lock, and unique-correct-submission behavior. |
| Participant accounts | `ctf.services.participant.accounts`; `lifecycle`; `bulk_import`; `management.services`; `config.auth`; `CTFAccountBoundaryMiddleware` | Keep isolated-account creation, password policy, group/profile marking, login, password change, capacity, and cleanup server-owned. |
| Ranges/live state | `ctf.services.range/*`; `ctf.bridges`; `cms.services.get_range_target_instances`; `shared.enums.RangeSource`; existing range API and Channels projection; `frontend/src/features/mission-control/guacamole.ts` | Keep CTF provenance and lifecycle server-side; live state is advisory and reconciles through canonical reads. Adapt CMS through the CTF bridge and return an explicit participant-safe target projection (`uuid`, `name`, `private_ip`, `os_type`) rather than forwarding raw provisioned-instance dictionaries. Reuse the existing protocol-parameterized Guacamole session hook; do not create a CTF access workflow. |
| Files | `ctf.services.attachment`; `ctf.s3`; `ctf.inspection`; `shared.uploads.inspection` | Preserve extension, size, bounded header, streaming text, hash, storage, ownership, and participant availability gates. |
| Flags/validators | `ctf.services.challenge`; `ctf.validators`; `ctf.services.regex_policy`; HTTP-validator DNS-rebinding guardrails | Never validate flags in React, expose stored/submitted flags, or bypass regex/HTTP/programmable validator policy. |
| Audit/logging | `shared.audit`; `ctf.services.audit`; `config.middleware.RequestIDMiddleware`; `shared.log_sanitize`; ECS logging config | Keep audit at service/workflow boundaries; log safe ids and request ids, never credentials, flags, invite material, signed URLs, or content. |
| Accessibility/design | `frontend/src/components/ui/*`; `frontend/src/app/state-map.ts`; #1302 and #1368 design artifacts | Reuse accessible dialogs, alerts, tables, tabs, focus management, skeletons, status mapping, and AA tests. |
| Enforcement | `.importlinter`; `.importlinter`-backed layer checks; `scripts/adr_guard/adr_guard.py`; `.github/workflows/_quality.yml` | Preserve Python layering and SPA lint/typecheck/test/build/e2e, API-contract, Django, and ADR gates. |

## Cross-Cutting Layers The Design Must Pass

- **Page/session authentication:** SPA-owned CTF pages start after a Django
  session exists. `platform_spa_host` primes CSRF; unsafe API requests pass
  `CsrfViewMiddleware` and DRF `SessionAuthentication` with `X-CSRFToken`.
  CTF login, required password change, logout, and provider flows remain Django
  and provider owned.
- **API-token authentication:** `ApiTokenAuthentication` remains first and
  fail-closed. `HasActiveCTFActor`, `HasCTFEndpointScope`, `HasCTFOrganizer`,
  `HasCTFParticipant`, and `HasCTFRole` remain the canonical HTTP gates. Browser
  code never stores or sends `shf_` tokens.
- **Account boundary:** `CTFAccountBoundaryMiddleware` continues to confine
  marked temporary accounts to participant-owned `/ctf/` and `/api/v1/ctf/`
  surfaces, plus the exact `/api/v1/mission-control/guacamole/` broker prefix
  needed for owner-authorized range sessions (#1740), and forces password
  change before any of them. The exception must not widen to Mission Control
  NGFW, range lifecycle/history, credentials, uploads, agents, or scenarios.
  SPA catch-alls must not swallow `/ctf/change-password/`, `/ctf/login/`,
  `/logout/`, unsafe legacy handlers, or unrelated platform paths.
- **Object/privacy authorization:** event ownership, event-scoped eligible
  participant resolution, disqualification, challenge availability, file
  access, solve-history ownership, scoreboard visibility/freeze, and organizer
  service checks all remain server-side. Route guards and hidden controls are
  advisory only.
- **Payload/shape validation:** explicit DRF serializers validate HTTP and
  query shapes; existing `_parse_body_object` is only a compatibility parser.
  CTF services, model `clean()`/`full_clean()`, enums, password validators,
  regex policy, flag validators, bulk-import validation, and upload inspection
  remain the deeper gates. Client checks improve ergonomics only.
- **Secret handling:** session cookies, CSRF tokens, API tokens, bootstrap
  credentials, password overrides, invite material, submitted/stored flags,
  validator configuration, challenge solutions, private range addresses,
  provider payloads, and signed file URLs must not enter static bundles,
  browser storage, URLs, logs, analytics, schemas/examples, snapshots,
  screenshots, GitHub metadata, or process argv. Challenge descriptions and
  organizer-authored content are untrusted text unless an accepted sanitizer
  explicitly permits markup.
- **Config shape:** rollout is a non-secret Django boolean, default off, read
  per request, surfaced in the typed bootstrap payload, and recorded through
  `config/_env_manifest.py` plus regenerated `config/env-manifest.json`. Do not
  use Vite environment variables. Deployment manifests need no secret binding
  for a default-off flag; any explicit environment override must use the
  canonical runtime-env rendering path.
- **Error envelope:** canonical failures use
  `{"error":{"code","message","details?","request_id?"}}` through
  `shared.api.errors`. Preserve `Retry-After` for throttling. Never serialize a
  `CTFError.__str__`, traceback, SQL/provider error, flag, credential, or signed
  URL. Frontend code uses `ApiError`, including field details and request id.
- **Logging/observability:** the SPA sends `X-Request-ID`,
  `RequestIDMiddleware` echoes it, and server logging/audit uses safe ids and
  `shared.log_sanitize`. Submission outcomes, credentials, participant emails,
  challenge content, flags, solution text, attachment URLs, and raw exception
  details are not browser diagnostics.
- **Persistence/concurrency:** PostgreSQL models, transactions, row locks,
  partial unique constraints, materialized leaderboard updates, scheduled
  tasks, and CMS range/outbox/reconciler paths remain authoritative. TanStack
  cache and websocket state are disposable projections.
- **Storage/runtime exposure:** attachment bytes continue through the existing
  bounded server upload/storage path and inspection rules. #1372 introduces no
  shell commands, temp-file workflow, cloud CLI, Terraform/Kubernetes mutation,
  secret-bearing environment value, or sensitive argv.
- **Import/layer boundary:** CTF may use its public bridges and `shared`
  contracts; cross-app access goes through public service facades. Do not import
  CMS/engine private modules or models into frontend/API presentation, and do
  not add direct `cyberscript` imports outside `shared`.
- **Accessibility:** challenge solving, scoreboards, organizer tables/forms,
  destructive confirmation, validation, polling, and live updates meet WCAG
  2.1 AA: semantic landmarks/headings, keyboard access, visible focus, labels
  and descriptions, non-color status, announced async results, focus recovery,
  reduced motion, and usable reflow/zoom.

### Range-access contract amendment (#1740)

The function named `ctf.views.api.ranges.api_range_access` is legacy dead code:
the runtime `/api/v1/ctf/range/access/` route is actually implemented by
`ParticipantRangeAccessView`, and that operation is already committed in
`openapi/v1.json`. Retire the SPA consumer and the dead legacy callable, but do
not silently delete the published v1 operation or its response component.
ADR-040 classifies route/response removal as a breaking change; the v1
compatibility operation must be marked deprecated and retained until a parallel
major plus migration window authorizes removal. If #1740 is interpreted as
requiring the HTTP operation itself to disappear immediately, that scope must
first be reconciled with ADR-040 rather than bypassing the breaking-change gate.

## Extensibility Seams

- **Route-ownership seam:** CTF prefix, feature flag, safe-method dispatch,
  legacy fallback, route-name stability, client routes, and nav metadata are
  the parameters. Participant and organizer pages use one host mechanism while
  keeping their distinct permission policies.
- **Actor/context seam:** typed reads carry an explicit event id or challenge id
  where the resource is scoped; active-event bootstrap is only the default
  selection. This permits a future multi-event switcher without reintroducing
  unscoped participant lookup.
- **Projection seam:** separate participant-safe and organizer-detail
  serializers may compose shared public fields, but permission-sensitive fields
  are selected server-side. A future challenge field is added to the relevant
  projection, not hidden after over-fetching.
- **Scoring seam:** generated types represent scoring mode, team/individual
  rankings, bracket filter, visibility, and freeze explicitly. New scoring
  modes extend server strategies and the one UI projection, not client formulas.
- **Live-state seam:** canonical reads hydrate and reconcile state; existing
  Channels transport may refresh projections, with bounded cancel-on-unmount
  polling where no socket exists. Unsafe actions are never auto-retried.
- **Upload seam:** a shared same-origin multipart request path is parameterized
  by endpoint, form data, abort signal, and progress callback while retaining
  CSRF/request-id/error behavior. It must remain distinct from the existing
  cross-origin presigned PUT helper, whose credential rules differ.

## Whole-Repo Scope

#1372 implementation must evaluate these surfaces together:

- Architecture/design: ADR-001, ADR-013, ADR-016, ADR-029; #1121, #1300,
  #1368, #1369, #1328, #1329, and this note.
- Frontend: `frontend/src/router.tsx`, `src/api/*`, `src/app/*`,
  `src/components/*`, `src/features/mission-control/upload*` as transport
  precedent only, and the new CTF feature boundary.
- Shell/config: `config/urls.py`, `config/settings.py`, `_env_manifest.py`,
  `env-manifest.json`, `_drf_settings.py`, `api_bootstrap.py`, `middleware.py`,
  `shared/spa_host.py`, and CTF page URL dispatch.
- CTF HTTP/contracts: `ctf/api/*`, `ctf/urls.py`, `ctf/views/_access.py`,
  `_parsing.py`, `views/api/*`, and participant/organizer HTML views as parity
  evidence only.
- CTF domain: `ctf/models/*`, `services/*`, `bridges.py`, `enums.py`,
  `exceptions.py`, `validators.py`, `inspection.py`, and `s3.py`.
- Cross-cutting backend: `shared/api/*`, `shared/api_tokens/*`, `shared/auth.py`,
  `shared/audit.py`, `shared/errors.py`, `shared/log_sanitize.py`,
  `shared/uploads/*`, `management.services`, `cms.services`, `engine.services`,
  Channels/ASGI auth, cache/rate-limit settings, email, and storage config.
- Legacy rollback/evidence: `templates/ctf/**` and CTF static JS/CSS remain
  independent rollback surfaces, not SPA dependencies.
- Enforcement if touched: `.github/workflows/**`, `.importlinter`, layer checks,
  `scripts/adr_guard/adr_guard.py`, API-contract generation/breaking-change
  checks, frontend ESLint/Vitest/axe/Playwright, Django tests, and build/static
  asset checks.

## Gotchas And Anti-Patterns

- Do not create a CTF shell, router, fetch wrapper, query client, error class,
  DTO package, status enum, validation layer, exception hierarchy, scoring
  calculator, or client workflow engine.
- Do not conflate UX mode with role, participant with user, active event with
  authorized event, event owner with global organizer, team with bracket, CTF
  range with Mission Control range, challenge visibility with release, or a
  public scoreboard with a participant/organizer scoreboard.
- Do not reuse organizer event/challenge payloads for participants and hide
  `solution`, flags, validator configuration, unreleased hints/files, or private
  monitoring fields in React. Data not authorized must not cross the wire.
- Do not turn organizer-created isolated-account enrollment into public
  self-signup, expose/reveal bootstrap passwords in the SPA, or let user/profile
  claims self-grant organizer authority.
- Do not duplicate form/model/service validation in TypeScript. In particular,
  keep event timing, team settings, challenge release/prerequisites, scoring,
  attempt/cooldown, flag, regex/HTTP validator, capacity, and upload policy on
  the server.
- Do not compute points, rank, hint cost, challenge availability, range
  readiness, or destructive-action eligibility as client authority.
- Do not publish the current generic CTF wrappers merely by deleting the schema
  exclusion, and do not hand-maintain CTF interfaces beside generated types.
- Do not render challenge/event/notification content with `dangerouslySetInnerHTML`
  or an unsanitized Markdown renderer.
- Do not send multipart through the JSON client by dropping CSRF/request ids,
  and do not reuse the credential-free presigned-S3 helper for same-origin CTF
  upload without preserving session semantics.
- Do not auto-retry flag submissions, hint purchases, registration/import,
  notifications, range actions, scoring changes, or destructive mutations.
- Do not remove, redirect, or catch-all-shadow legacy login, password-change,
  page, form-action, scoreboard, or rollback routes in #1372.
- Do not weaken privacy tests, rate limits, transactions/constraints, upload
  inspection, audit strictness, CSP/browser policy, API-contract checks, layer
  enforcement, ADR guard, or accessibility gates.

## Non-Goals

- No implementation of SPA routes/pages/components, API clients, serializers,
  endpoints, flags, schema publication, migrations, services, tests, or route
  cutover in this preflight.
- No retirement of legacy CTF routes, templates, form handlers, login/password
  flows, or the intentionally retained legacy scoreboard endpoint.
- No redesign of the locked visual system, logo, favicon, or product-wide IA
  outside the open #1368 CTF flows.
- No new identity provider, public registration model, auth token, password
  lifecycle, role model, permission policy, scoring engine, flag validator,
  range orchestrator, websocket auth scheme, upload/storage system, audit store,
  or persistence model.
- No implementation of separately tracked API consolidation beyond minimal
  typed `/api/v1/` gaps required by #1372 acceptance criteria.
- No cloud infrastructure, background worker, SSR server, second origin, CORS
  posture, secret-delivery path, Terraform, or Kubernetes change.
