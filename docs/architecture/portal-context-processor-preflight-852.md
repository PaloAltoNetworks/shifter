# Portal Context Processor Preflight (#852)

Status: pre-implementation guidance

Date: 2026-06-07

Tracking issue: <https://github.com/Brad-Edwards/Shifter/issues/852>

## Scope Boundary

Issue #852 is diagnostic and design work. The shipping contract is to quantify
the hidden per-rendered-request cost of portal context processors on event
paths, identify material contributors, decide whether #684 is enough, and
document where global context is truly required.

This is not a portal scaling, terminal websocket, or ASGI process-manager
change. Adjacent ownership stays with:

- #851 for portal health, overload observability, and autoscaling signals.
- #847 for terminal websocket capacity and runtime placement.
- #174 for the production ASGI process manager.
- #684 for Mission Control terminal/context module refactoring only where that
  refactor explicitly covers the measured context construction work.

## Architecture Decisions

- Treat context construction as request-path work, not as a harmless template
  detail. Measurement must run through rendered pages with `request=` so Django
  invokes the same context processors and included sidebars as production.
- Keep domain boundaries intact. Mission Control presentation code may call
  `cms.services`; CTF role/range integration stays through `ctf.bridges` and
  CTF services; CMS and Engine stay presentation-free.
- The current full active-range payload is a terminal-page concern. The global
  sidebar needs at most an active-range indicator, not `RangeContext.instances`,
  runtime private IP overlay, `connection_urls`, or `terminal_instances`.
- Role/navigation context is a navigation concern. Do not create a second CTF
  role schema or duplicate group/profile/event logic to make one page faster.
- Default optimization posture is request-scoped reuse or page-scoped context,
  not cross-request caching. Cross-request caches for roles, range state, or
  runtime IPs are stale and security-sensitive unless a follow-up explicitly
  owns invalidation.
- #684 covers #852 only if it lands evidence-backed changes to active-range /
  terminal context construction. CTF navigation cost, rendered-page
  measurement, and safe-page documentation are separate unless #684 is amended
  to include them.
- No new ADR is required before measurement. If a follow-up introduces a new
  metrics framework, cache policy, public diagnostic endpoint, or new context
  ownership abstraction, that follow-up should add or update architecture docs.

## Current Context Surface

Global template context processors are registered in
`shifter/shifter_platform/config/settings.py` under `TEMPLATES`.

| Processor | Current work | Safe global need |
| --- | --- | --- |
| `mission_control.context_processors.active_range` | For authenticated users, calls `cms.services.get_active_range()`, may join CMS range rows with engine runtime IPs, filters instances for CTF-only users, may call `get_scenario()`, and builds terminal JSON payloads. | Full payload is required by `mission_control/terminal.html`. The sidebar only needs a cheap `has_active_range` indicator. |
| `mission_control.context_processors.terminal_cdn_assets` | Reads `TERMINAL_CDN_ASSETS` from settings. | Safe to leave global because it is settings-only; only terminal templates need it. |
| `shared.context_processors.user_permissions` | Calls `shared.auth.can_edit_cms_authoring()` for sidebar visibility. | Required by the shared Mission Control sidebar for Threat Research/CMS links. |
| `ctf.context_processors.ctf_navigation` | Calls `ctf.bridges.get_user_role()`, which checks Django groups and may resolve `UserProfile.active_ctf_event_id` plus `CTFEvent`. | Required by `ctf/base.html` and sidebars for CTF navigation decisions. |

Representative rendered pages for evidence:

- Mission Control: dashboard, terminal with no active range, terminal with a
  provisioning range, terminal with a ready range.
- CTF participant event paths: dashboard, event, challenges, challenge detail,
  range, scoreboard, team.
- Anonymous/auth paths: login/session-backed pages as a no-DB context baseline.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #852 |
| --- | --- | --- |
| Global context registration | `config/settings.py` `TEMPLATES[...]["context_processors"]` | Change global registration only with rendered-page tests proving every included template still gets required context. |
| Active range ownership/query | `cms.services.get_active_range()`, `_validate_caller_user()`, `RangeInstance` ownership filter | Keep user ownership in CMS services. Do not move range authorization into templates, JavaScript, or request path checks. |
| Range/instance shape | `shared.schemas.RangeContext`, `InstanceContext`, `mission_control.utils.build_connection_urls()` | Reuse the existing template-safe DTO and URL builder for full terminal payloads; no parallel terminal DTO. |
| Runtime IP overlay | `cms.services._common._resolve_runtime_ips()` and `_instance_contexts_from_range_spec()` | Keep runtime IP lookup best-effort and joined by instance UUID. Do not duplicate range-spec flattening. |
| CTF role context | `ctf.bridges.UserRole`, `get_user_role()`, `shared.auth` group constants | Reuse the existing role bridge and predicates. Do not invent a second role object or group-name literals. |
| CTF participant/event resolution | `ctf.views._get_active_participant()`, `_get_participant_for_challenge()`, CTF services | Preserve active-event scoping for multi-event users; do not replace it with unscoped first-row participant lookups. |
| CMS authoring permissions | `shared.auth.can_edit_cms_authoring()` and `shared.context_processors.user_permissions()` | Keep the Threat Research/staff policy in `shared.auth`; no duplicate permission checks in templates. |
| Template JSON safety | Django `json_script`, `RangeContext` / `InstanceContext` validators | Continue embedding terminal payloads through `json_script`; no inline JSON interpolation. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()` | Measurements/logs use aggregate counts, route names, user IDs, and sanitized IDs only. |
| Error envelopes | `shared.errors.UserFacingError`, `safe_user_message()`, `classify_user_message()` | Any HTTP diagnostic surface must use authored messages; context processor failures stay fail-soft and logged server-side. |
| Tests | Existing context/template tests plus Django `Client`, `RequestFactory`, `CaptureQueriesContext` | Add rendered-page evidence in the existing pytest/Django style rather than a one-off script that bypasses context processors. |
| Import boundaries | `.importlinter` contracts | Mission Control must not import CTF; CTF must not import Mission Control or Engine; CMS must not import presentation layers. |

## Cross-Cutting Layers

- Auth surface: rendered portal pages enter through Django middleware,
  `AuthenticationMiddleware`, `@login_required`, CTF decorators, and request
  user objects. Anonymous users must keep the current fast empty-context
  behavior. Any page-scoped or lazy context decision must be server-derived from
  the view/template need, never from a query string, header, or client flag.
- Authorization surface: active-range data must still come through
  `cms.services.get_active_range(user)` or a CMS-owned lower-cost equivalent
  that enforces the same user ownership. CTF navigation must still use
  `ctf.bridges.get_user_role()` and active-event scoping. Templates and
  JavaScript are consumers, not policy gates.
- Secret-handling surface: context data may include internal private IPs,
  instance UUIDs, websocket paths, role flags, and event IDs. These are
  authorized UI data, not secrets, but they must not be exposed on anonymous
  pages or logged in raw per-user detail. Do not log cookies, session IDs,
  signed Guacamole URLs, Redis URLs, DB settings, SSH material, or full process
  environments while measuring.
- Env/config surface: global context registration lives in Django settings.
  Avoid adding env knobs for this diagnostic. If a later follow-up adds one, it
  must use the existing settings helpers and provider renderers, and it must be
  non-secret.
- Validation surface: keep using `RangeContext` / `InstanceContext` Pydantic
  validators, including private-IP normalization, and CMS user validators. Do
  not add a duplicate schema just to model partial context.
- OS/runtime exposure: measurement artifacts should be local test output,
  sanitized logs, or documentation. Do not introduce a public endpoint, shell
  command with secret-bearing argv, or process/environment dump to collect query
  counts.
- Error-envelope surface: context processors currently fail soft to empty
  context and log exceptions. Preserve that browser-facing behavior unless a
  follow-up deliberately changes a page-level contract. Any user-visible
  diagnostic response must use authored error text from `shared.errors`.
- Observability surface: use ECS-formatted logs and sanitized IDs for any
  temporary or permanent measurement logging. A new metrics emitter is out of
  scope for #852 and belongs under the #851 capacity-signal contract.
- Persistence surface: no schema, migration, audit table, or durable event log
  is needed for this diagnostic. Store evidence in tests/docs/artifacts, not in
  portal database tables.
- Template/XSS surface: terminal JSON stays in `json_script`; private IPs and
  instance names continue to pass through Django escaping and DTO validation.

## Extensibility Seam

The seam is context scope and depth, parameterized by server-owned page need:

- `none`: anonymous or pages that do not need authenticated navigation state.
- `nav`: role flags, `can_access_threat_research`, and a cheap active-range
  indicator for shared sidebars.
- `ctf`: CTF role plus active event for CTF navigation and participant views.
- `terminal_full`: full `RangeContext`, scenario name, connection URLs,
  terminal instance JSON, and runtime private IP overlay.

Keep that seam out of CMS/Engine model logic. CMS services may expose domain
queries, but they should not know template names, paths, or sidebar behavior.
Future pages should be able to opt into a deeper context without re-editing the
range projection, role bridge, or template payload schema.

## Evidence Bar

The measurement artifact that closes #852 should report, at minimum:

- Query count, SQL time, and wall time for each global context processor on the
  representative rendered pages above.
- The same measurements for no active range, provisioning range, and ready range
  with runtime IP state.
- Service-call attribution for `get_active_range()`, runtime IP lookup,
  `get_scenario()`, `get_user_role()`, `get_user_profile()`, CTF event lookup,
  and group membership queries.
- p50/p95 context construction time over repeated rendered requests, with warm
  and cold-ish DB/queryset states called out if both are captured.
- A table of pages where each context field is required: full terminal context,
  active-range indicator, CTF nav flags, CMS authoring permission, or none.
- A decision statement: #684 covers the measured work, or specific follow-up
  issues are needed for active-range scoping, CTF role reuse, measurement
  harness hardening, or safe-context documentation.

## Gotchas

- A lazy object is not automatically cheaper. If `icon_sidebar.html` or
  `ctf/base.html` touches it on every page, the same DB work still happens.
- `ctf_navigation` and CTF participant views both resolve role/active-event
  context today. Measure duplicate group/profile/event work before choosing a
  request-scoped reuse point.
- `active_range` mutates `range_context.instances` when filtering CTF-only
  users. Reusing the same `RangeContext` object across independent consumers or
  requests would make that mutation dangerous.
- Runtime IP lookup is best-effort and can hide engine/CMS cost behind a
  successful page render. Count service calls, not only SQL queries.
- `mission_control.dashboard.html` uses CTF-only flags for view-only behavior,
  but it does not need full terminal payload construction.
- `ctf/participant/range.html` already does explicit range target lookup in the
  view. Do not mix that page-scoped range data with global Mission Control
  terminal context.
- Broad cross-request caching of role or range context can leak stale access
  after group, active-event, participant status, or range lifecycle changes.
  Prefer request-scope reuse unless a follow-up owns invalidation.
- Import-linter forbids the tempting shortcut of centralizing all context in a
  shared helper that imports every app.

## Anti-Patterns

- Passing `request.path`, template names, or a "needs terminal" flag into CMS or
  Engine services.
- Moving ownership/range/status/role checks into templates, JavaScript, or a
  client-selectable context flag.
- Creating duplicate range DTOs, CTF role schemas, permission helpers,
  exception hierarchies, logging formatters, metrics frameworks, or validation
  layers.
- Treating query count alone as proof. Runtime service calls, wall time, p95,
  and duplicate group/profile/event work matter too.
- Making active-range context globally lazy and declaring success without
  rendered-page measurements showing fewer queries/service calls.
- Adding a public diagnostic endpoint for query counts or p95 timing.
- Logging raw emails, signed Guacamole URLs, cookies, session data, Redis auth
  URLs, DB credentials, private keys, request bodies, or raw exception text.
- Weakening `.importlinter`, ADR guard, CSRF/session auth, CTF decorators, or
  template escaping to simplify measurement.

## Non-Goals

- No implementation, context processor rewrite, cache, middleware, settings
  change, endpoint, schema change, or database migration in this preflight.
- No redesign of portal autoscaling, health probes, Daphne/Gunicorn runtime,
  terminal websocket transport, Guacamole bootstrap, CTF scoring, or range
  provisioning.
- No new Ground Control requirement; the GitHub issue is the source of truth.
- No new repo-wide metrics, logging, exception, schema, or auth framework.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must also run the stack-native checks for changed
surfaces, especially import-linter for Python package-boundary changes and
targeted pytest suites for rendered context/template behavior.
