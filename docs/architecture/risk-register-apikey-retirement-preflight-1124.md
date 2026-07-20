# Risk-Register APIKey Retirement Preflight (PLAT-106 / #1124)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: PLAT-106, "Unified DRF API Surface"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1124>

This note narrows the PLAT-106 DRF/API-token guardrails to retiring the
deprecated risk-register `X-API-Key` principal. It is intentionally not an
implementation plan.

## Scope Boundary

Issue #1124 retires the legacy `risk_register.models.APIKey` runtime
authentication path in favor of the platform-wide `shared.api_tokens.ApiToken`.
After the cutover, the risk-register HTTP/JSON API must authenticate only
through:

- `shared.api_tokens.authentication.ApiTokenAuthentication` with exact
  `risk:read` / `risk:write` scopes; or
- DRF `SessionAuthentication` with the existing session, CSRF, staff, and
  Cognito-group checks.

The retirement includes every legacy credential management surface that can mint
or accept an `rr_live_...` key: DRF authenticators, risk-register API key
viewsets/serializers/routes, browser HTML key create/revoke views, Django admin
mutation affordances, OpenAPI security schemes, tests, and developer docs.

Historical records are a separate data-retention concern. Existing
`APIKey` rows, `Comment.author_apikey` references, and `AuditLog` rows may need
to remain readable until a deliberate data migration proves they can be removed.
Keeping archival metadata is acceptable; keeping a runtime authentication or
minting path is not.

## Architecture Decisions

- Default to a hard retirement when inventory shows no active external
  consumers: remove the authenticating `APIKeyAuthentication` path from
  risk-register DRF views and remove the `/api/v1/api-keys/` management surface.
- If active key holders exist, migrate them by issuing replacement
  `ApiToken`s through the existing `shared.api_tokens` creation path with
  explicit `risk:read` and/or `risk:write` scopes. Do not try to transform
  stored legacy rows into usable platform tokens: raw `rr_live_...` values are
  unrecoverable, and raw `shf_...` tokens must be shown exactly once.
- If a notice-period compatibility response is required, make it
  rejection-only: a supplied `X-API-Key` may produce a fixed API error and an
  audit signal, but it must never return an authenticated principal, bypass
  scopes, or appear as a valid OpenAPI security scheme.
- Keep platform token lifecycle in `shared.api_tokens`. Risk-register must not
  grow a new token-management API, token serializer vocabulary, token hashing
  scheme, or token self-service scope as part of this retirement.
- Preserve risk-register domain authorization. A token scope admits a
  programmatic caller to the endpoint class; `risk_register.access` still proves
  the token owner belongs to an allowed Cognito group, and session callers still
  need staff/superuser permission where the current API requires it.
- Keep `risk_register.access` on runtime principals only. After #1124, that
  means `shared.api_tokens.ApiToken` plus authenticated sessions; the archival
  `risk_register.models.APIKey` model must not be imported into access-policy
  branches or accepted as a `request.auth` shape.
- Treat `AuditLog.ActorType.APIKEY` and `AuditLog.EntityType.APIKEY` as durable
  historical enum values unless a separate audit-taxonomy migration updates the
  model, serializers, admin, docs, and tests together. Do not partially rename
  them in one layer.
- Do not overload `Comment.author_apikey` with `ApiToken`. If token-authored
  comments need user attribution, resolve that through `ApiToken.created_by` or
  a deliberately designed generic principal field, not by reusing the legacy
  foreign key.
- No new ADR is needed unless implementation changes enforceable import,
  auth, audit, workflow, or data-retention guardrails beyond this guidance.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1124 |
| --- | --- | --- |
| Platform DRF auth | `config/_drf_settings.py`, `ApiTokenAuthentication`, DRF `SessionAuthentication` | Risk-register endpoints should use the shared session/bearer-token path. No legacy app-local authenticator should remain as an accepting credential path. |
| Scope admission | `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope` | Use `RISK_READ` and `RISK_WRITE`; do not add app-local booleans, wildcard scopes, or APIKey-specific scopes. |
| Token lifecycle | `shared/api_tokens/{models,admin,audit,scopes,permissions}.py` | Replacement tokens use the one-time raw-token, bounded-TTL, revocation, and audit behavior already implemented there. |
| Risk authorization | `risk_register.access.principal_has_risk_register_access`, `HasRiskRegisterCognitoGroup`, `IsStaffSessionOrToken` | Keep Cognito-group and staff/session semantics. Runtime token branches accept `ApiToken` only; the archival `APIKey` model must not remain in access-policy imports or `request.auth` type checks. Remove only the legacy key principal, not the second-stage domain gates. |
| Legacy key surfaces | `risk_register.models.APIKey`, `risk_register.api.authentication`, `risk_register.api.views.APIKeyViewSet`, `risk_register.api.serializers`, `risk_register.views.apikey_*`, `APIKeyAdmin` | Disable or remove runtime mint/auth surfaces deliberately. Preserve archival data only when needed for comments or audit history. |
| Audit | `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `get_client_ip`, `get_request_id`, `shared.api_tokens.audit` | Use existing audit helpers and trusted client-IP resolution. Do not add a parallel credential-retirement audit table. |
| Error envelopes | `shared.api.errors.api_exception_handler`, `api_error_response` | API retirement errors use the platform envelope and fixed messages. Do not echo raw header values, hashes, prefixes, or provider traces. |
| OpenAPI | `shared.api.schema`, `config/api_urls.py`, `drf_spectacular` | Remove the deprecated `RiskRegisterApiKeyAuth` scheme once no accepting authenticator remains. Do not leave `X-API-Key` in generated schema or examples. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log counts, route names, request ids, and safe token ids/fingerprints only. Never log raw legacy keys, raw platform tokens, cookies, CSRF tokens, or full auth headers. |
| Tests | `rest_framework.test.APIClient`, `tests/risk_register/test_api_token_access.py`, `tests/shared/test_api_tokens_*`, `tests/config/test_settings.py` | Extend HTTP-boundary and schema tests. Avoid helper-only tests for a credential cutover. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: every risk-register API request passes through
  `ApiTokenAuthentication` before `SessionAuthentication`. Invalid bearer input
  keeps the existing fail-closed 401 behavior. A supplied legacy `X-API-Key`
  must not authenticate; if it is still recognized for transition feedback, the
  recognizer is rejection-only and runs before any session fallback ambiguity.
- Scope surface: token callers pass through `require_scope(scopes.RISK_READ,
  scopes.RISK_WRITE)`. A legacy key has no scopes and must not be upgraded into
  an implicit all-risk scope.
- Session and CSRF surface: browser callers continue using session cookies and
  DRF `SessionAuthentication`; unsafe session-authenticated requests stay CSRF
  protected. Do not add `csrf_exempt` or a CSRF-exempt session authenticator as
  part of APIKey retirement.
- Risk-register authorization surface: after auth, existing
  `principal_has_risk_register_access` and staff/session checks still run. For
  token callers, group admission is based on `ApiToken.created_by`; the token
  string itself is not a user, role, or Cognito group.
- Migration and inventory surface: inventory active legacy keys by row metadata
  only: count, owner, `created_at`, `last_used_at`, `expires_at`, and
  `revoked_at`. Do not print, export, email, log, or snapshot `key_hash`, raw
  keys, raw replacement tokens, cookies, or auth headers.
- Replacement-token surface: replacement credentials are created through
  `ApiToken.create_token` or the existing Django admin path so scope validation,
  TTL caps, one-time display, verifier hashing, and audit events remain
  centralized. Do not mint tokens with ad hoc SQL, fixtures, shell literals, or
  management-command output that writes raw tokens to process logs.
- Persistence surface: dropping or altering `APIKey` must account for
  `Comment.author_apikey`, historical audit actor/entity values, admin/search
  expectations, and migrations. If historical rows exist, prefer an archival,
  non-authenticating model/table until a data-retention migration is explicitly
  reviewed.
- Error-envelope surface: authentication failures, retired-header responses,
  missing scopes, and missing risk-register group membership return the shared
  API error envelope with sanitized messages and request id when available. Do
  not return `str(exc)` from legacy authenticator code.
- OpenAPI surface: generated schema must advertise only `ApiTokenAuth` and
  session auth for risk-register endpoints. `X-API-Key`, `rr_live_...`, legacy
  key create responses, and raw token examples must disappear from schema and
  docs once the accepting path is retired.
- Logging and observability surface: audit legacy-key revocation or transition
  events through `risk_register.services` / `shared.api_tokens.audit`. Do not
  add per-request success audit rows for platform tokens; keep coalesced
  `last_used_at` for liveness.
- Config and OS exposure surface: no new runtime setting is expected. If a
  temporary cutover flag or management command is unavoidable, bind settings via
  existing `config.settings` parsers and `config/env-manifest.json`, and keep
  raw tokens out of argv, shell history, CI output, ConfigMaps, and docs.
- Import-boundary surface: `shared` must not gain a dependency on
  `risk_register.api.authentication`. Remove the old OpenAPI extension rather
  than keeping a shared schema hook for a retired app-local authenticator.

## Extension Points

- Legacy disposition belongs in one place: hard removal, archival-only model, or
  rejection-only notice shim. Do not scatter retirement branches across every
  viewset, serializer, permission, and URL module.
- Token audience remains the central scope registry. If a future risk-register
  integration needs narrower access, add a reviewed central scope and reuse
  `require_scope`; do not resurrect per-app API keys.
- Historical-principal retention is a data-retention decision. If comments or
  audits need long-term display of old key names, preserve a read-only archival
  projection instead of keeping authentication code alive.
- A future token self-service API would need a separate requirement, scopes, and
  escalation review. It should extend `shared.api_tokens`, not risk-register.

## Whole-Repo Scope

Likely implementation surfaces are:

- `shifter/shifter_platform/risk_register/models.py` and migrations, depending
  on whether `APIKey` becomes archival-only or is removed.
- `shifter/shifter_platform/risk_register/api/{authentication,permissions,serializers,views,urls}.py`.
- `shifter/shifter_platform/risk_register/{views,urls,admin}.py` and any
  templates/nav that expose legacy key creation or revocation.
- `shifter/shifter_platform/risk_register/access.py` and
  `risk_register/services.py` for principal resolution and audit attribution.
- `shifter/shifter_platform/shared/api/schema.py` for removing the legacy
  OpenAPI security extension.
- `shifter/shifter_platform/shared/api_tokens/**` only for reuse or focused
  tests; do not redesign the token model for this issue.
- `shifter/shifter_platform/documentation/docs/technical/dev/api.md` and any
  operator/developer docs that mention `X-API-Key`.
- Tests under `shifter/shifter_platform/tests/risk_register`,
  `tests/shared`, and `tests/config`.

Whole-repo checks in scope include ADR guard, import-layer checks when imports
change, DRF settings invariants, generated schema coverage, API-token scope
behavior, CSRF/session behavior, and shared error-envelope behavior.

## Gotchas And Anti-Patterns

- Do not leave `APIKeyAuthentication` declared on risk-register viewsets after
  claiming the API accepts only session and platform tokens.
- Do not silently keep `/api/v1/api-keys/` as a legacy key creation API.
- Do not leave browser HTML or Django admin paths that can mint fresh
  `rr_live_...` keys unless they are explicitly converted to archival/read-only
  views.
- Do not add scopes to `APIKey`; it is the principal being retired, not a
  second platform token to upgrade.
- Do not auto-migrate by copying hashes or attempting to reconstruct raw keys.
  Legacy hashes cannot produce usable platform tokens.
- Do not print replacement raw tokens from scripts, CI logs, management-command
  stdout, or shell examples.
- Do not drop the legacy table while `Comment.author_apikey` or historical
  audit display still depends on it.
- Do not conflate `AuditLog.ActorType.APIKEY` with permission to keep the old
  `APIKey` model active. The enum can be historical while runtime auth moves to
  `ApiToken`.
- Do not leave `RiskRegisterApiKeyAuth`, `X-API-Key`, or `rr_live_...` examples
  in OpenAPI or developer docs after cutover.
- Do not turn API-key retirement into a risk-register workflow rewrite,
  severity/status schema rewrite, or new public token-management product.

## Non-Goals

- No implementation in this preflight note.
- No migration of Mission Control, CTF, or CMS endpoints.
- No redesign of `shared.api_tokens`, OAuth/OIDC, Django sessions, CSRF, or
  risk-register Cognito-group policy.
- No new token self-service API, token-management scope, public API posture,
  rate-limiting system, audit table, or logging framework.
- No Terraform, Kubernetes, workflow, or runtime secret-delivery change unless
  a later implementation adds a real deployment-facing setting or script.
