# CTF DRF API Migration Preflight (PLAT-106 / #1121)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: PLAT-106, "Unified DRF API Surface"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1121>

This note narrows the repo-wide PLAT-106 DRF conventions to the CTF JSON API
migration. It is intentionally not an implementation plan.

## Scope Boundary

Issue #1121 migrates the CTF HTTP/JSON API from ad-hoc Django function views
onto the platform DRF surface. DRF owns only HTTP concerns: authentication,
scope admission, request/response serializers, parser selection, error
envelope, pagination/filter query validation, and OpenAPI metadata.

Application behavior stays in the existing CTF services and bridge seams:
event ownership, organizer and participant role checks, participant
event-scoping, challenge availability, submission rate limits, file inspection,
notification rendering, range lifecycle orchestration, scoring, and persistence.

Out of scope: CTF magic-link register/exchange, server-rendered CTF pages,
Mission Control and CMS migrations, CTF role redesign, token self-service, new
API token concepts, new score models, and cloud/runtime configuration changes.

## Architecture Decisions

- Mount the canonical CTF API under `/api/v1/ctf/` through
  `config/api_urls.py`. `ctf/urls.py` remains the HTML and temporary legacy
  route surface. If legacy `/ctf/api/...` compatibility is retained, bind it to
  the same DRF behavior intentionally and keep its compatibility envelope
  narrow and temporary.
- Reuse the platform DRF defaults from `config/_drf_settings.py`:
  `shared.api_tokens.authentication.ApiTokenAuthentication` first, then DRF
  `SessionAuthentication`, with `shared.api.errors.api_exception_handler`.
  Do not add CTF-local authenticators or CSRF exemptions.
- Reuse `shared.api.permissions.IsAuthenticatedSessionOrApiToken` and
  `shared.api_tokens.permissions.require_scope(...)` for non-public endpoints.
  CTF scopes already live in `shared.api_tokens.scopes`:
  `ctf:event:read`, `ctf:event:write`, and `ctf:play:write`.
- Treat scopes as HTTP-boundary admission only. They do not prove organizer
  ownership, participant membership, active-event selection, challenge
  availability, or staff/platform admin status.
- Resolve the CTF actor from the authenticated session user or from
  `ApiToken.created_by`, mirroring `mission_control.api.permissions`. Token
  calls with no active owning user must fail before CTF services run.
- Keep CTF role and object policy in the existing incumbents:
  `ctf.bridges.get_user_role`, `ctf.services.participant.is_active_participant`,
  `ctf.services.participant.get_participant_by_user`, and
  `ctf.services.authorization.assert_actor_owns_event`.
- Preserve the explicit public scoreboard exception only for the public
  scoreboard surface. It must still enforce event existence, scoreboard
  visibility/freeze rules, bracket query validation, and scoring's exclusion of
  disqualified participants. Do not make score timelines, submissions,
  challenge files, organizer scoreboard/admin views, or range endpoints public
  as collateral.
- Use DRF serializers to replace `_parse_body_object`, `_get_body_str`, and
  `_parse_body_uuid` at the HTTP boundary. Do not fork service-layer validation
  rules or move business validation out of services.
- Use DRF parser selection deliberately. JSON endpoints stay JSON-shaped;
  challenge-file upload needs multipart handling while still delegating to
  `ctf.services.attachment.add_challenge_file` for extension, size, and content
  inspection.
- Keep CTF exception mapping centralized in the DRF layer. Map
  `CTFValidationError` and `CTFStateError` to 400, `CTFNotFoundError` to 404,
  `CTFPermissionError` to 403, `CTFRateLimitError` to 429 with `Retry-After`
  where available, and `CTFRangeError` to a bounded 400/502-style response only
  after reviewing the service error. Do not serialize `str(exc)` or
  `CTFError.to_dict()`.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1121 |
| --- | --- | --- |
| API mount and schema | `config/api_urls.py`, `/api/v1/`, `drf_spectacular` | Register CTF once through the platform v1 mount; no app-local schema/docs route. |
| DRF auth and errors | `config/_drf_settings.py`, `shared.api.errors`, `shared.api.permissions` | Use shared defaults and envelope; no CTF-local auth or exception framework. |
| Token scope registry | `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope` | Add or use scopes centrally only; no hard-coded scope strings in methods. |
| Token principal | `shared.api_tokens.models.ApiToken.created_by` | A token acts as its owning active user for CTF role/object checks. |
| CTF role bridge | `ctf.bridges.get_user_role` | Do not duplicate group names or conflate CTF Organizer, CTF Participant, staff, or Threat Research. |
| Participant eligibility | `ctf.services.participant.eligible_participant_q`, `is_active_participant`, `get_participant_by_user` | Preserve disqualified-participant exclusion and event-scoped participant resolution. |
| Organizer ownership | `ctf.services.authorization.assert_actor_owns_event`, existing resolver helpers | Scopes never authorize another organizer's event. |
| Service facades | `ctf.services` public facade and targeted CTF subpackages already used by views | DRF views call services; serializers do not own workflows or persistence. |
| Range orchestration | `ctf.services.range`, `ctf.bridges` to `cms.services` | Keep background provisioning/coalescing and CMS boundary semantics. |
| File security | `ctf.services.attachment`, `ctf.inspection`, `ctf.s3`, `shared.uploads.inspection` | Multipart parsing is HTTP-only; inspection and S3 behavior remain service-owned. |
| Notification templates | `ctf.services.email_template` and per-type placeholder allowlists | DRF serializers may check shape, but template grammar remains service-owned. |
| Client IP/audit context | `risk_register.services.get_client_ip`, request-id middleware | Keep trusted IP resolution for submissions; do not invent a second audit helper. |
| Logging hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log sanitized IDs and authored messages only; never tokens, flags, invite tokens, or URLs. |
| Tests | `rest_framework.test.APIClient`, existing CTF API flow tests, Mission Control token tests | Migrate behavior tests to the canonical `/api/v1/ctf/` routes and add scoped-token coverage. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: DRF authentication must preserve fail-closed bearer-token
  behavior. Missing bearer credentials may use session auth; malformed,
  expired, revoked, or wrong-prefix bearer credentials must return 401 and must
  not fall through to a logged-in browser session.
- CSRF surface: unsafe browser/SPA calls authenticate through
  `SessionAuthentication` and remain CSRF-protected. Token-authenticated
  programmatic calls do not rely on cookies and must not require a CSRF token.
- Scope surface: every non-public CTF endpoint declares its scope from
  `shared.api_tokens.scopes`. Organizer/event reads use `ctf:event:read`;
  organizer/event mutations use `ctf:event:write`; participant play mutations
  use `ctf:play:write`. If file download, participant submission history, or
  scoreboard reads need a distinct programmatic audience, add a new central
  scope rather than overloading `ctf:event:*` or `ctf:play:write`.
- Domain authorization surface: after scope admission, organizer endpoints still
  prove CTF organizer role and event ownership; participant endpoints still
  prove active, non-disqualified membership in the route's event; mixed
  organizer/participant surfaces still check the specific object, not just any
  CTF role.
- Payload validation surface: DRF serializers replace raw body parsing for JSON,
  UUID, enum, integer, datetime, list, multipart, and query parameter shapes.
  Domain validation stays in CTF services, model validation, and template/file
  inspection helpers.
- Error-envelope surface: canonical `/api/v1/ctf/` routes return the shared
  `{"error": {...}}` envelope with request id when present. Legacy flat
  `{"error": "..."}` responses are a compatibility concern only if old routes
  are deliberately retained.
- Rate-limit surface: `CTFRateLimitError` from flag submission and attempt
  limits keeps HTTP 429, `Retry-After`, and safe retry metadata. Do not collapse
  it into a generic serializer 400.
- Secret-handling surface: raw API tokens, Authorization headers, cookies, CSRF
  tokens, invite/magic-link tokens, submitted flags, stored flag values,
  validator config secrets, presigned S3 URLs, uploaded file bodies, and
  participant credentials must not appear in logs, audit JSON, OpenAPI examples,
  docs snippets, process argv, test snapshots, or error envelopes.
- OS/runtime exposure surface: no new env binding is expected. If
  implementation adds a setting, use `config.settings` env parsers and update
  `config/env-manifest.json`; do not pass bearer tokens, signed URLs, or flags
  on command lines in examples or tests.
- Import-boundary surface: CTF may import `shared`, `cms.services`, and
  `management.services` per `scripts/check_layer_imports/layer_imports.yaml`.
  It must not import `mission_control` or `engine` directly; cross-domain calls
  stay through `ctf.bridges` or approved service facades.
- OpenAPI surface: schema generation must see the canonical CTF routes,
  serializers, parser types, response envelopes, auth, and required scopes.
  Examples must be placeholders only and must not include real flags, tokens,
  invite links, or presigned URLs.

## Extensibility Seams

- Scope declaration seam: keep required scopes as class-level/data-like
  declarations that DRF permissions and OpenAPI metadata can both read. Do not
  hard-code them inside method bodies.
- Actor seam: centralize session/token-to-CTF-actor resolution once for the CTF
  API so a future service-account-owned-token decision has one place to extend.
- Public-read seam: if public scoreboard API behavior expands, put that behind
  a narrow allowlist and dedicated visibility policy, not by weakening the base
  CTF API permission.
- Route seam: versioned routing belongs in `config/api_urls.py`; a future
  `/api/v2/ctf/` should be route/schema work, not a service rewrite.
- Query/filter seam: bracket, status, ordering, pagination, and future filters
  should be serializer/filterset-declared so they remain validated and visible
  in OpenAPI.

## Gotchas And Anti-Patterns

- Do not treat `ctf:event:write` as ownership of all CTF events.
- Do not treat `ctf:play:write` as membership in every event or as access to
  hidden/unreleased challenges.
- Do not resolve participants without event scope on challenge-, event-, range-,
  or active-event-specific routes.
- Do not regress disqualified participant exclusion by checking only
  `registered_at`.
- Do not expose the score timeline or file-download API through the public
  scoreboard exception.
- Do not skip `ctf.services.attachment` inspection by reading multipart uploads
  directly in serializers.
- Do not return submitted flags, stored flag values, validation exception text,
  invite tokens, presigned URLs, or uploaded file details in error envelopes or
  schema examples.
- Do not duplicate `_parse_body_object` as a new parser helper; use serializers.
- Do not copy Mission Control legacy-envelope compatibility unless CTF legacy
  URLs are intentionally retained and tested.
- Do not add CTF imports from Mission Control or Engine to preserve old
  redirect/range behavior.
- Do not broaden notification send behavior that currently returns HTML for
  browser Accept headers unless the legacy compatibility path explicitly keeps
  that browser route separate from the canonical API route.

## Non-Goals

- No implementation in this preflight note.
- No new ADR; existing ADR-001 import boundaries, PLAT-102 auth guidance, and
  the PLAT-106 shared DRF preflight cover the enforceable architecture.
- No migration of CMS, Mission Control, server-rendered CTF pages, CTF magic
  links, or token management.
- No CTF model/schema rewrite, scoring redesign, range orchestration redesign,
  or notification-template grammar expansion.
- No new public API posture beyond the explicitly public scoreboard exception.
