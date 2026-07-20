# Auth And Session Audit Logging Preflight (#162)

Status: pre-implementation guidance

Date: 2026-07-04

Issue: GitHub #162, "Add audit logging for authentication and session events"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as filling audit coverage gaps in the existing portal audit layer,
not as a new logging framework, SIEM exporter, authentication system, session
store, or provider abstraction.

Keep these concepts separate:

1. Identity-provider evidence: password, MFA, Hosted UI, and provider-side risk
   events happen in Cognito and are not observable inside the Django callback.
2. Application OIDC evidence: the Django app observes callback arrival, state
   handling, token exchange, token validation, user lookup/provisioning, and
   local session creation.
3. Browser authentication session evidence: login/logout and provider/session
   exchange events for Django sessions.
4. Access session evidence: terminal WebSocket and Guacamole RDP/SSH access
   sessions are separate from the Django browser session.
5. Durable audit evidence versus observability logs: `AuditLog` rows are the
   reviewable audit record; ECS JSON log lines are the structured operational
   stream.

## Architecture Decisions

- `risk_register.models.AuditLog` remains the canonical durable audit store.
  All new auth/session audit writes must go through `risk_register.services`
  (`AuditEvent`, `audit_auth_event`, `audit_session_event`,
  `audit_log_from_request`, or a narrow extension there). Do not add a parallel
  auth-audit model, per-provider table, JSONL file, or ad hoc log-only schema.
- ECS JSON logging already exists in `config.logging.ECSFormatter` and
  `config._logging_config`. Acceptance criteria that call for structured JSON
  logs should be satisfied by the existing formatter plus sanitized structured
  fields, not by hand-serialized JSON strings in auth code.
- Existing request correlation already exists in
  `config.middleware.RequestIDMiddleware` and
  `risk_register.services.get_request_id()`. Do not add a second correlation ID
  middleware unless this one is deliberately replaced everywhere.
- OIDC callback success/failure belongs at the OIDC boundary:
  `config.oidc.ShifterOIDCBackend` for provider/user processing and, if needed,
  a thin wrapper around `mozilla_django_oidc.views.OIDCAuthenticationCallbackView`
  for callback-level failures that happen before or around backend
  authentication. Avoid scattering callback audit logic into unrelated views.
- Token validation and token-exchange failures may raise before
  `ShifterOIDCBackend.authenticate()` reaches its existing `user is None`
  branch. The implementation must cover real callback exceptions from
  `get_token()`, `verify_token()`, JWKS lookup, nonce/state validation, and
  claims/user creation without logging raw tokens or provider response bodies.
- Cognito password/MFA success and failure should be handled as provider-side
  audit evidence. The app can document and, if necessary, reference the
  CloudWatch/Cognito log source, but it must not claim app-level callback logs
  prove password or MFA attempts the app never observed.
- Browser logout should reuse `config.views.logout_view` and
  `audit_auth_event(action=AuditLog.Action.LOGOUT, ...)`. Capture the user
  identity and request context before calling Django `logout()`, because the
  session is flushed afterward.
- Access-session lifecycle should reuse `audit_session_event()` and
  `AuditLog.EntityType.SESSION`. Existing terminal WebSocket code records
  connect/disconnect/access-denied; timeout-specific close reasons can be
  represented as bounded context or, if truly needed, one deliberate enum
  extension with migration/admin/API visibility.
- Guacamole bootstrap rows are not the session audit store.
  `GuacamoleBootstrapRequest` records signed URL bootstrap and delivery
  lifecycle. If #162 audits Guacamole access-session starts, call the platform
  audit facade at the launch/delivery boundary without storing Guacamole URLs,
  tokens, RDP passwords, SSH keys, or bootstrap result URLs in audit state.
- No new ADR is required if the implementation stays within these existing
  auth, audit, logging, and session boundaries. A new audit durability queue,
  provider-log ingestion pipeline, telemetry platform, or auth/session model
  redesign would need separate design/ADR work.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #162 |
| --- | --- | --- |
| Durable audit store | `risk_register.models.AuditLog` | Extend choices only with a migration and existing admin/API visibility. |
| Audit facade | `risk_register.services.AuditEvent`, `audit_log`, `audit_auth_event`, `audit_session_event`, `audit_log_from_request` | Put new request-context or event-shaping behavior here instead of duplicating schemas in auth views. |
| Request attribution | `get_client_ip`, `select_trusted_client_ip`, `get_request_id`, `RequestAudit` | Preserve trusted rightmost XFF hop semantics and middleware request IDs. |
| Audit health/failure policy | `audit_log(..., strict=...)`, `audit_role_sync`, `risk_register.audit_health`, `config.health_checks` | Do not hide audit failures; use existing degraded health behavior for best-effort writes and strict writes only for safety-control mutations. |
| OIDC auth | `config.oidc.ShifterOIDCBackend`, `provider_logout_url`, `mozilla_django_oidc` callback/request views | Keep Cognito/OIDC token handling in the provider boundary; do not reimplement the OIDC flow. |
| Identity Platform auth | `config.identity_platform.login_with_identity_token`, `IdentityPlatformBackend`, `config.views.identity_platform_session` | Preserve fixed error envelopes and audited login/create behavior if shared helpers are generalized. |
| Logout | `config.views.logout_view` | Audit before session flush; keep POST-only logout and provider-specific logout routing. |
| Dev auth | `config.dev_auth.dev_login`, `dev_logout`, `config.user_type_sync.sync_user_type` | Do not broaden dev-auth reachability or treat it as production Cognito evidence. |
| Terminal sessions | `mission_control.consumers.SSHConsumer`, `mission_control.terminal_sessions`, `risk_register.services.audit_session_event` | Extend existing connect/disconnect/access-denied semantics; no per-byte/per-keystroke audit. |
| Guacamole bootstrap | `mission_control.guacamole_bootstrap`, `GuacamoleBootstrapRequest`, `mission_control.views._guacamole_bootstrap` | Treat signed URLs as secret-bearing; audit metadata only at launch/delivery boundaries. |
| Structured logs | `config.logging.ECSFormatter`, `config._logging_config` | Use normal module loggers and `extra` fields the formatter understands; do not emit nested JSON strings as messages. |
| Log sanitization | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Sanitize log identifiers; never log tokens, cookies, auth headers, raw provider bodies, or full Guacamole URLs. |
| Error envelopes | `shared.errors.classify_user_message`, fixed auth error codes | Browser/API failures must not echo provider exceptions, token payloads, stack traces, or audit persistence details. |
| Import boundaries | `.importlinter` | Keep cross-app access through existing facades; do not make CTF import Mission Control or Engine, or Management import app layers. |

## Cross-Cutting Layers

Security layers the design must pass:

- Auth surface: OIDC requests pass through `mozilla_django_oidc` state/nonce
  handling, token exchange, token validation, claim verification, user
  lookup/provisioning, and Django login. Log app-observed success/failure at
  these boundaries without weakening state, nonce, callback URL, or claim
  checks.
- Identity-provider boundary: Cognito owns password and MFA outcomes. App audit
  rows may state `oidc_callback_*` or token-validation outcomes; Cognito
  CloudWatch/provider logs remain the evidence for password/MFA events.
- Secret-handling surface: authorization codes, ID/access tokens, cookies, CSRF
  tokens, Authorization headers, OIDC client secrets, JWKS payloads, Guacamole
  URLs, RDP passwords, SSH keys, and full provider response bodies must not be
  logged, copied into audit state, emitted to error envelopes, placed in argv,
  or written to docs/test snapshots.
- Request attribution surface: HTTP audit uses `get_client_ip()` and
  `get_request_id()`. WebSocket audit uses the same trusted-hop policy via
  `select_trusted_client_ip()`. Do not trust leftmost XFF, `Host`, `X-Real-IP`,
  or ad hoc request parsing in auth/session call sites.
- Config shape and validators: OIDC/Identity Platform settings stay in
  `config._oidc_settings`; logging settings stay in `_logging_config`; request
  middleware order stays in `config.settings`. New non-secret knobs, if any,
  must use existing settings parser patterns and update env manifests/renderers
  only when deployment needs them. Python changes must pass Ruff, import-linter,
  and ADR guard.
- OS/runtime exposure: do not shell out from auth/session paths, do not put
  tokens or secrets in process arguments, deployment logs, Terraform/Kubernetes
  manifests, ConfigMaps, health bodies, metrics labels, or local fallback files.
- Error-envelope surface: expected auth failures return fixed redirects or
  authored JSON errors. Raw `HTTPError`, `SuspiciousOperation`, JWT, Firebase,
  database, and audit persistence details stay server-side and sanitized.
- Audit persistence surface: `AuditLog` JSON fields must hold bounded,
  serializable metadata only: email, Cognito sub, provider name, outcome,
  reason code/category, session id, session type, range/target identifiers when
  non-secret, request id, source IP, and user agent. Avoid arbitrary exception
  strings or full request/provider payloads.

Maintainability incumbents the implementation must build on:

- `risk_register.services` for audit event shaping, failure policy, request
  context, trusted source IP, and request ID.
- `config.oidc`, `config.identity_platform`, `config.views.logout_view`, and
  `config.dev_auth` for auth-provider-specific behavior.
- `mission_control.consumers.SSHConsumer` and
  `mission_control.guacamole_bootstrap` for access-session boundaries.
- `config.logging.ECSFormatter` plus `shared.log_sanitize` for structured,
  sanitized observability.
- Existing tests under `tests/risk_register`, `tests/mission_control`,
  `tests/config`, and provider-specific auth tests; prefer persisted
  `AuditLog` assertions over first-party patch-only tests.

Extensibility seam:

Keep one provider-neutral audit event shape in `risk_register.services`, with
provider/outcome/reason as parameters. The next likely variation is another
auth provider or another access-session protocol; that should add provider or
session-type values at the audit facade call sites, not a new audit schema or
duplicate callback/session lifecycle logic. If timeout distinctions matter,
model the seam as a bounded close reason (`user_close`, `idle_timeout`,
`max_duration`, `error`, `access_denied`) rather than new free-form action
taxonomies in every transport.

## Whole-Repo Scope

Likely in scope for the implementation that follows:

- `shifter/shifter_platform/config/oidc.py`
- `shifter/shifter_platform/config/views.py`
- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/risk_register/models.py`, migrations, admin, and
  API serializers only if action/entity vocabulary changes
- `shifter/shifter_platform/config/logging.py` only if ECS label support needs
  narrow extension
- `shifter/shifter_platform/mission_control/consumers.py`
- `shifter/shifter_platform/mission_control/views/_guacamole*.py`,
  `mission_control/api/guacamole.py`, and `mission_control/guacamole_bootstrap.py`
  only if Guacamole session-start audit is included
- Tests under `shifter/shifter_platform/tests/risk_register`,
  `tests/config`, `tests/mission_control`, and OIDC/Identity Platform auth tests
- Cognito/CloudWatch operator documentation only if the implementation claims
  provider-side password/MFA audit coverage

Usually out of scope:

- Replacing Cognito, Identity Platform, `mozilla-django-oidc`, Django sessions,
  Guacamole, terminal WebSockets, or the Risk Register audit table.
- Building provider-log ingestion, SIEM export, a durable audit queue, public
  diagnostics, or a new operator UI.
- Auditing every HTTP request, API-token success, terminal byte stream, or
  Guacamole polling attempt.
- Changing Terraform, Kubernetes, ALB, WAF, Redis, or runtime topology unless a
  chosen provider-log or runtime setting truly requires deployment wiring.

## Gotchas And Anti-Patterns

- Do not conflate Cognito login/MFA events with Django OIDC callback events.
  The app cannot log password/MFA failures it never sees.
- Do not rely on `ShifterOIDCBackend.authenticate()` returning `None` as the
  only failure path; token exchange, JWKS, JWT, nonce/state, and user creation
  errors can raise before that branch.
- Do not store raw exception text as the audit `reason` when the exception may
  include token endpoint URLs, response bodies, codes, client ids, or provider
  internals. Use bounded reason categories.
- Do not add another correlation ID middleware, log formatter, audit table,
  exception hierarchy, source-IP parser, auth-provider wrapper, or session
  repository while the existing seams cover the need.
- Do not log or audit Guacamole signed URLs, OIDC tokens, authorization codes,
  RDP credentials, SSH keys, cookies, CSRF tokens, or full request headers.
- Do not use `Host`, `request.get_host()`, leftmost XFF, or `X-Real-IP` as an
  audit source-IP authority.
- Do not make every audit write strict. Login/logout/access-session audit can
  remain best-effort with explicit degraded health unless the write is a safety
  control for a mutation.
- Do not use free-form context strings as the only machine-readable event
  taxonomy. If tooling needs to filter event kinds, add a bounded field or enum
  through the canonical audit facade.
- Do not weaken POST-only logout, CSRF-protected session exchange, OIDC state
  checks, import-linter, ADR guard, Ruff, or existing sanitized error envelopes
  to make audit capture easier.

## Non-Goals

- No implementation in this preflight note.
- No formal Ground Control requirement or traceability work.
- No replacement for Cognito CloudWatch/provider audit evidence.
- No new ADR unless the implementation changes repo-wide audit durability,
  auth/session policy, provider-log ingestion, or architecture guardrails.
- No backfill or repair of historic missing auth/session audit rows.
- No change to accepted auth-provider support or role/group semantics.

## Validation

For this docs-only preflight, run:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/auth-session-audit-logging-preflight-162.md --level fast
```

Future implementation touching `shifter/shifter_platform` must also run the
repo-required Python checks from `.gc/plan-rules.md`, especially Ruff and
import-linter, plus full ADR guard before completion.
