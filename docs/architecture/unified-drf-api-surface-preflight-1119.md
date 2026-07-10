# Unified DRF API Surface Preflight (PLAT-106 / #1119)

Status: pre-implementation guidance

Date: 2026-06-25

Requirement: PLAT-106, "Unified DRF API Surface"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1119>

This note sets the architecture guardrails for the shared DRF conventions and
OpenAPI schema. It is intentionally not an implementation plan.

ADR-027 note: legacy experiment and script APIs were removed by issue #1195.
References below to `cms.experiments` describe the pre-removal state and are not
current implementation guidance.

## Scope Boundary

Issue #1119 establishes the common API contract. It does not migrate Mission
Control, CTF, or CMS endpoints; those migrations are separate milestone issues.

The target boundary is:

- DRF owns HTTP concerns: authentication, scope authorization, request/response
  serialization, query parameter validation, error envelope, pagination,
  filtering, and OpenAPI metadata.
- Existing services own application behavior: ownership, role checks, state
  transitions, workflow orchestration, persistence, audit-worthy mutations,
  cloud calls, upload validation, and secret materialization.
- The platform API is versioned under `/api/v1/`. Existing HTML routes may keep
  browser-only helpers during migration, but new non-public HTTP/JSON API
  endpoints must not be added as ad-hoc `JsonResponse` function views.

## Architecture Decisions

- Use the PLAT-102 foundation as the canonical auth path:
  `shared.api_tokens.authentication.ApiTokenAuthentication` first, then DRF
  `SessionAuthentication`. A supplied invalid bearer token fails closed and must
  not fall through to a session.
- Declare every non-public API endpoint's token scopes from
  `shared.api_tokens.scopes`. Scopes are additive HTTP-boundary admission, not
  object ownership or domain authorization.
- Keep session authorization explicit. DRF token scope permission admits token
  callers; session callers still need app/domain permission classes that reuse
  existing predicates such as `shared.auth.can_edit_cms_authoring`, CTF
  organizer/participant checks, risk-register Cognito group access, and
  Mission Control ownership services.
- Keep the legacy `risk_register` `APIKey` only as a compatibility concern for
  current risk-register consumers until #1124 retires it. New DRF endpoints must
  not import or accept that app-local key principal.
- Add one platform DRF exception handler and make it the only API error-envelope
  path. It should select fixed/sanitized user messages via
  `shared.errors.classify_user_message`, include request correlation, and expose
  serializer field details only when they are validation data rather than raw
  exception text.
- Configure OpenAPI once at the platform DRF layer. The schema and docs routes
  should live under `/api/v1/` and should not become app-local schema views. The
  schema is an endpoint inventory, so default to protecting it with the same
  non-public API auth posture unless a separate public-docs decision is made.
- Pagination and filtering defaults belong in `REST_FRAMEWORK` and shared DRF
  conventions. Manual filtering inside `get_queryset()` is acceptable legacy
  compatibility, not the preferred pattern for new migrated endpoints.
- No new ADR is needed for this conventions issue. ADR-001 import boundaries,
  the PLAT-102 decision record, and existing architecture guardrails already
  cover the boundary; update ADR docs only if implementation changes enforceable
  guardrails or exceptions.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for PLAT-106 |
| --- | --- | --- |
| DRF settings and version mount | `config.settings.REST_FRAMEWORK`, `config.urls` `/api/v1/` include | Extend the existing block and mount pattern; do not add per-app API roots with divergent auth or schema behavior. |
| Programmatic auth | `shared.api_tokens.authentication.ApiTokenAuthentication`, `shared.api_tokens.models.ApiToken` | Use platform bearer tokens. Do not use `risk_register.models.APIKey` for new endpoints. |
| Scope registry | `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope` | Add scopes centrally and compose the shared permission; no wildcard scopes or app-local boolean permissions. |
| Session and role policy | `shared.auth`, `risk_register.access.principal_has_risk_register_access`, `ctf.views._access`, service-layer ownership checks | Preserve existing role semantics for sessions and service calls; do not treat scopes as roles. |
| Service facades | `cms.services`, `cms.experiments.services`, `ctf.services`, `engine.services`, `risk_register.services` | DRF views call public service facades. Do not import private service submodules or duplicate workflows in serializers. |
| Request/domain schemas | DRF serializers, `shared.schemas`, `cms.experiments.schemas`, `cms.scenarios.schema`, existing upload validators | Serializers validate HTTP shapes; existing Pydantic/domain schemas remain authoritative for domain contracts. |
| Error leakage controls | `shared.errors.classify_user_message`, `UserFacingError`, current CTF/CMS/Mission Control fixed JSON messages | Centralize the DRF envelope; do not return `str(exc)`, stack traces, provider payloads, or ownership details. |
| Audit | `risk_register.services.audit_log_from_request`, `AuditEvent`, `get_client_ip`, `get_request_id`, `shared.api_tokens.audit` | Reuse the existing audit store and trusted source-IP resolver. Do not introduce a second API audit table. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log route/action/request id and sanitized identifiers only. Never log bearer tokens, cookies, CSRF tokens, presigned URLs, or signed Guacamole URLs. |
| Secret-bearing APIs | `mission_control.guacamole_bootstrap`, upload-token services, `shared.cloud` adapters | Keep one-time URLs/tokens short-lived, single-use where already designed, and out of schema examples/logs/audit state. |
| Config binding | `config.settings` env parsers, `config/_env_manifest.py`, `config/env-manifest.json`, platform `pyproject.toml` | New settings or dependencies are platform-level changes; update the manifest when new env bindings are added. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR-001 | API code must respect app boundaries. Put shared DRF/auth helpers in `shared`, not in one feature app. |
| Tests | Existing DRF token tests, app JSON view tests, risk audit tests | Add behavior tests at the HTTP boundary plus focused serializer/exception-handler tests; do not only test helper functions. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: requests pass through Django authentication middleware and DRF
  authenticators. Browser/SPA clients use session cookies and DRF
  `SessionAuthentication`, so unsafe methods remain CSRF-protected by
  `CsrfViewMiddleware`. Programmatic clients use `Authorization: Bearer shf_...`
  via `ApiTokenAuthentication`; invalid bearer input returns 401 and never
  falls through to the session credential on the same request.
- Scope authorization surface: token requests pass through
  `require_scope(...)` with scopes from `shared.api_tokens.scopes.KNOWN_SCOPES`.
  Missing scopes return 403 with a fixed message. Session requests pass through
  this token gate but must be checked by sibling session/domain permissions.
- Domain authorization surface: CTF event ownership, participant event scoping,
  challenge availability, CMS authoring permission, scenario access,
  Mission Control range/NGFW ownership, risk-register Cognito group access, and
  upload-token ownership remain in their existing services/predicates. A scope
  admits a caller to an endpoint class; it does not authorize a specific object.
- Payload and query validation surface: DRF serializers validate HTTP JSON and
  query parameters. Existing Pydantic schemas and validators keep validating
  scenario definitions, experiment inputs, credential specs, uploads, and
  service/domain invariants. Do not split the same business rule across a DRF
  serializer and a service schema.
- Error-envelope surface: the DRF exception handler maps DRF
  `ValidationError`, `AuthenticationFailed`, `NotAuthenticated`,
  `PermissionDenied`, `NotFound`, throttling, and existing domain exceptions
  (`CMSError`, `CTFError`, validation/state/not-found errors) into one bounded
  envelope. Full exception detail is logged server-side with sanitizers, not
  serialized.
- Secret-handling surface: Authorization headers, raw API tokens, session
  cookies, CSRF tokens, invite tokens, upload tokens, presigned URLs, provider
  ID tokens, Guacamole JSON-auth payloads, signed Guacamole URLs, SSH keys, RDP
  passwords, and cloud secret references must not appear in logs, audit JSON,
  schema examples, docs snippets, process argv, environment files, ConfigMaps,
  GitHub summaries, or error envelopes.
- Logging and observability surface: logs go through ECS formatting and
  `shared.log_sanitize`; request correlation uses `RequestIDMiddleware` /
  `X-Request-ID`. Durable audit uses `risk_register.services`. Authentication
  success should continue using coalesced `last_used_at` rather than per-request
  audit rows unless a separate volume decision is made.
- Config and dependency surface: OpenAPI/filtering dependencies belong in
  `shifter/shifter_platform/pyproject.toml` and `uv.lock`. DRF schema/filtering
  settings belong in `REST_FRAMEWORK`. Any new environment-driven API setting
  must use the existing settings parsers and be represented in
  `config/env-manifest.json`.
- OS/runtime exposure surface: API examples, docs, tests, management commands,
  and smoke scripts must not pass bearer tokens or secret-bearing URLs on shell
  command lines. Prefer headers sourced from secret stores, files with correct
  permissions, or stdin-managed tooling when examples are needed.
- Import-boundary surface: app API modules may import `shared` and their public
  service facades. They must not add direct CTF-to-Mission-Control/Engine or
  Mission-Control-to-CTF imports, direct `cyberscript` imports outside `shared`,
  or private service-submodule dependencies.
- OpenAPI surface: generated schema must reflect required auth and scopes and
  must not expose secrets in examples/defaults. Schema generation should inspect
  endpoint declarations rather than relying on prose-only scope documentation.

## Extensibility Seams

- API version seam: keep the version in the URL mount (`/api/v1/`) and schema
  title/version settings, not embedded in services or serializer class names.
  A future `/api/v2/` should be a routing/schema decision, not a domain rewrite.
- Scope declaration seam: if OpenAPI needs machine-readable required scopes,
  extend the shared `shared.api_tokens.permissions` pattern once so permissions
  and schema metadata read from the same declaration. Do not hard-code scopes in
  method bodies or duplicate them in schema decorators.
- Error-envelope seam: the DRF exception handler is the extension point for new
  domain exception mappings, error codes, request-id fields, or future i18n. Do
  not add app-local exception handlers.
- Router seam: each migrated app may expose app-local DRF URL modules, but the
  platform mount and schema inclusion stay centralized under `config.urls` and
  `/api/v1/`.
- Filtering seam: endpoint-specific filter parameters should be serializer- or
  filterset-declared so adding a new filter is local to that endpoint and visible
  in OpenAPI. Avoid unvalidated free-form query parameters.

## Whole-Repo Scope

Likely implementation will touch some of these surfaces:

- `shifter/shifter_platform/pyproject.toml` and `uv.lock` for OpenAPI/filtering
  dependencies.
- `shifter/shifter_platform/config/settings.py`, `config/urls.py`, and, if env
  settings are added, `config/_env_manifest.py` plus
  `config/env-manifest.json`.
- `shifter/shifter_platform/shared/api_tokens/*`, `shared/errors.py`,
  `shared/log_sanitize.py`, `shared/auth.py`, and any new shared DRF API helper.
- `shifter/shifter_platform/risk_register/api/*`,
  `risk_register/access.py`, and `risk_register/services.py`.
- Mission Control JSON APIs in `mission_control/urls.py` and
  `mission_control/views/_ranges.py`, `_ngfw.py`, `_credentials.py`,
  `_uploads.py`, `_files.py`, `_guacamole.py`, and `_guacamole_bootstrap.py`.
- CTF JSON APIs in `ctf/urls.py`, `ctf/views/api/*`, `ctf/views/_access.py`,
  `ctf/views/_parsing.py`, and `ctf.services`.
- CMS JSON APIs in `cms/experiments/urls.py`, `cms/experiments/views/*`,
  `cms/scenario_editor/urls.py`, `cms/scenario_editor/views_*`,
  `cms/scenarios/schema.py`, and `shared.schemas`.
- Tests under `tests/shared`, `tests/risk_register`, `tests/mission_control`,
  `tests/ctf`, `tests/cms`, and `tests/config`.
- Architecture enforcement and guidance: `.importlinter`,
  `scripts/adr_guard/adr_guard.py`, PLAT-102 architecture notes, and this file.

Usually out of scope for #1119:

- Terraform, Kubernetes, workflow, or runtime secret-delivery changes unless
  new settings or deployment-facing docs are introduced.
- Replacing OIDC, Identity Platform, CTF magic links, Django sessions, or the
  PLAT-102 token model.
- Migrating per-app endpoints, retiring legacy risk-register API keys, or
  redesigning CTF/CMS/Mission Control domain policies.

## Gotchas And Anti-Patterns

- Do not assume `REST_FRAMEWORK` defaults secure existing
  `/mission-control/api/...`, `/ctf/api/...`, experiments, or scenario-editor
  function views before they are migrated.
- Do not copy risk-register's legacy `APIKeyAuthentication` into new endpoints.
- Do not move business logic, object ownership, state transitions, cloud
  operations, upload inspection, or audit-worthy mutations into serializers or
  viewsets.
- Do not create duplicate DTOs, filter parsers, validation tables, exception
  hierarchies, audit stores, log formats, or token/scope concepts.
- Do not make schema docs public by accident; endpoint inventory and scope names
  are platform-sensitive until explicitly reviewed.
- Do not expose token management to tokens themselves unless a separate
  token-management scope and escalation review is accepted.
- Do not make browser session requests CSRF-exempt as part of unifying the API.
  Token-authenticated programmatic clients are distinct from cookie-authenticated
  browser clients.
- Do not put bearer tokens, presigned URLs, signed Guacamole URLs, cookies, or
  CSRF tokens in query strings, schema examples, command-line examples, logs, or
  audit state.
- Do not encode API version, auth policy, or scope names only in docs. The
  running DRF permissions and generated schema must carry the contract.
- Do not change public HTML routes or templates as collateral work for the
  conventions issue.

## Non-Goals

- Migrating Mission Control, CTF, CMS experiments, or scenario-editor endpoints.
- Removing legacy risk-register `APIKey` support.
- Designing a public unauthenticated API.
- Replacing Django sessions, OIDC, Identity Platform, or CTF magic links.
- Rewriting domain services, repositories, models, workflows, or upload/storage
  provider adapters.
- Adding rate limiting, token self-service APIs, OAuth client credentials, API
  gateways, or a new audit subsystem unless separately scoped.
