# API Token Authentication Preflight (PLAT-102 / #677)

Status: pre-implementation guidance

Date: 2026-06-22

Requirement: PLAT-102, "API Token Authentication"

This note sets the architecture guardrails for adding platform-wide API
authentication via browser sessions and scoped API tokens. It is intentionally
not an implementation plan.

## Scope Boundary

Treat PLAT-102 as a platform authentication and authorization-boundary change,
not as a broad RBAC rewrite, OAuth provider implementation, or public API
redesign.

The platform already has three relevant auth surfaces:

1. Browser sessions through Django auth, OIDC / Identity Platform, CSRF
   middleware, and `@login_required` / role decorators.
2. DRF API key authentication in `risk_register.api.authentication`, currently
   scoped to the risk-register API and lacking token scopes.
3. Function-based JSON APIs in Mission Control, CTF, CMS experiments, and the
   scenario editor, mostly protected by Django decorators and service-layer
   authorization rather than DRF permissions.

The implementation must cover all non-public API endpoints across those
surfaces. Updating only `REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]` is
not sufficient because most platform JSON endpoints are not DRF viewsets.

## Architectural Decisions

- Browser-based clients continue to authenticate with Django sessions. Session
  auth remains subject to Django CSRF protection on unsafe methods.
- Programmatic API tokens are a platform-wide principal, not a
  `risk_register`-only concept. The existing `risk_register.models.APIKey`,
  `risk_register.api.authentication.APIKeyAuthentication`, and audit behavior
  are incumbents to learn from, but they must not become an outward dependency
  imported by CTF, Mission Control, CMS, or shared platform code.
- If the existing risk-register `APIKey` is evolved or migrated, preserve a
  clear compatibility path for `/api/v1/` while moving platform-token concepts
  to a shared/platform-owned boundary. Do not create a second unrelated API-key
  model with a different hash, revocation, audit, and serializer vocabulary.
- Token scopes are an additive HTTP-boundary permission check. They do not
  replace service-layer ownership, role, state, participant, scenario, or
  resource availability checks.
- One canonical scope vocabulary should serve both DRF and Django function
  views. The expected shape is resource plus operation, for example
  `risk:read`, `risk:write`, `ctf:event:read`, `ctf:event:write`,
  `mission_control:range:write`, or equivalent. Avoid ad hoc booleans such as
  `can_access_ctf_api` scattered across apps.
- Token management is a browser-session admin operation unless a separate,
  explicit token-management scope is introduced. Staff/superuser or the
  existing platform admin predicate should create and revoke tokens; API tokens
  must not gain self-escalating management by accident.
- Raw token material is displayed exactly once at creation and is never stored,
  logged, written to audit state, sent in email, placed in URLs, or accepted via
  query parameters.
- Invalid bearer/API-token credentials must fail closed and must not fall back
  to session authentication for the same request. "No token supplied" may fall
  back to session auth; "bad token supplied" is an authentication failure.
- The public endpoint allowlist must be explicit. Existing public or special
  endpoints include `/`, `/health`, provider login/session exchange routes,
  OIDC routes, dev-login routes with their own environment/peer gate, CTF magic
  link registration/exchange, and CTF help. Everything else that is an API
  surface should require either a valid session or a valid scoped token.
- PLAT-102 is currently `DRAFT` with a `DOCUMENTS` link to GitHub issue #677.
  Implementation should transition the requirement to `ACTIVE` before creating
  `IMPLEMENTS` traceability links.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for PLAT-102 |
| --- | --- | --- |
| Browser session auth | `config._oidc_settings`, `config.oidc`, `config.identity_platform`, Django `AuthenticationMiddleware`, `CsrfViewMiddleware` | Keep browser session behavior and CSRF semantics intact. Do not make token auth a way to weaken session-cookie protections. |
| DRF auth | `REST_FRAMEWORK` in `config.settings`, `risk_register.api.authentication.APIKeyAuthentication` | Reuse the DRF integration pattern, but move platform-wide token logic out of app-local risk-register ownership. |
| Function-view auth | `@login_required`, `staff_member_required`, `shared.auth.threat_research_required`, `ctf.views._access` decorators | Add token coverage through a shared checker/decorator/middleware pattern that preserves each view's domain authorization. |
| Role and group predicates | `shared.auth` group constants and predicates, `ctf.bridges.get_user_role` | Do not duplicate role strings or conflate CTF Organizer with platform admin, Threat Research, staff, or superuser. |
| Request parsing | `ctf.views._parsing._parse_body_object`, DRF serializers, experiment Pydantic schemas, scenario YAML/schema validation | Keep body shape validation in the existing parser/schema layer. Token scope checks do not validate payload shape. |
| Error envelopes | `shared.errors.classify_user_message`, `UserFacingError`, `ctf.views._access._json_error`, DRF auth exceptions | Return fixed/sanitized authentication and authorization errors. Do not serialize raw token/auth exceptions. |
| Audit logging | `risk_register.models.AuditLog`, `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `get_client_ip`, `get_request_id` | Use the existing audit store and trusted source-IP resolver. Do not introduce a parallel auth audit table. |
| Log hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Log token prefixes or fingerprints only when needed. Never log raw token bytes or full headers. |
| Persistence patterns | Django models/migrations, indexes, admin read-only/audit patterns, existing `revoked_at` / `expires_at` conventions | Store only non-reversible token verifiers plus prefix metadata; keep revocation and expiry first-class queryable fields. |
| Config binding | `config.settings` env parsers, `config/env-manifest.json`, `config/_env_manifest.py`, `scripts/gcp/render_runtime_env.py` | Any token policy knob must be parsed in settings and reflected in the env manifest. Raw token values must never be runtime env or ConfigMap data. |
| Import boundaries | `.importlinter`, `shared`, public service facades, `ctf.bridges` | Platform token code should live where apps can depend on it without cross-layer imports or hidden conceptual coupling. |
| Architecture gates | `scripts/adr_guard/adr_guard.py`, `.importlinter`, `docs/adr/index.yaml` | If implementation changes guardrails or app boundaries, update ADR docs and run the required architecture checks. |

## Cross-Cutting Layers

### Security

- **Auth surface:** session auth goes through Django auth middleware and the
  existing provider backends. Token auth must have a single canonical
  authentication path for DRF and a matching path for function views. Bad token
  input fails closed before view logic runs.
- **Scope policy gate:** each protected API action must map to a required scope
  or small set of scopes. The checker should support the obvious future
  variation of a new resource/action scope without editing every token model,
  serializer, and permission class.
- **Domain authorization:** existing service-layer checks remain authoritative:
  CTF event ownership, participant event scoping, CMS authoring policy,
  scenario `enabled` / `staff_only`, Mission Control per-user range ownership,
  and risk-register admin-only access all still run after token scope admission.
- **Secret handling:** raw tokens, Authorization headers, cookies, CSRF tokens,
  invite tokens, provider ID tokens, and OIDC/Identity Platform secrets must not
  appear in logs, audit JSON, exception messages, query strings, URL fragments,
  process argv, generated env files, ConfigMaps, workflow summaries, or docs.
- **Persistence verifier:** do not store bare raw tokens. Prefer a random
  high-entropy token with an identifying prefix and a non-reversible verifier
  checked with constant-time semantics. The current risk-register SHA-256 shape
  is an incumbent compatibility concern, not a platform-wide standard to copy
  uncritically.
- **Revocation and expiry:** `revoked_at`, `expires_at`, and `last_used_at`
  belong in the durable model. If authentication results are cached, revoked and
  expired tokens must converge quickly and fail closed.
- **Error envelopes:** unauthenticated, invalid-token, expired-token,
  revoked-token, and insufficient-scope responses should be fixed messages with
  correct 401/403 semantics. Do not leak whether a token prefix exists beyond
  what is necessary for safe audit correlation.
- **CSRF:** token-authenticated programmatic calls may bypass CSRF only when
  they are authenticated by the bearer/API token path, not when a browser
  session cookie is the credential. Avoid broad `csrf_exempt` on shared views.
- **OS/runtime exposure:** token creation and automation examples must not pass
  tokens on command lines where they land in process listings or shell history.
  Prefer headers sourced from secret stores or stdin-managed tooling in docs.

### Maintainability

- Reuse `risk_register.services` for request audit context and audit writes.
  Direct calls to `AuditLog.log()` already exist in older code, but new
  cross-cutting auth work should use the service helpers unless there is a
  narrow reason not to.
- Reuse `shared.auth` for role predicates and shared policy helpers. Do not add
  app-local staff/Threat Research/CTF group string checks.
- Reuse the existing parser/schema layer in each app. Token work should not
  introduce duplicate DTOs for CTF event payloads, Mission Control range
  payloads, or experiment/script payloads.
- Keep token-specific exceptions small and at the auth boundary. Do not add a
  parallel exception hierarchy inside every app.
- Preserve app import boundaries. If a new installed app is chosen for tokens,
  decide and document its dependency direction explicitly rather than letting
  imports grow organically.

### Extensibility

The main extension point is the scope declaration/checker, not the token model.
The next likely changes are additional API resources, a read-only vs mutating
scope split, token-specific rate limits, and service-account-owned tokens. That
requires:

- a central scope registry or constants module;
- a shared `has_scope` / `require_scope` checker usable by DRF permissions and
  Django function views;
- endpoint declarations that are data-like and local to the route/view;
- token metadata that is not tied to a single app's resource model.

Do not encode scope meaning only in serializer validation, form fields, or free
text in an audit `context`.

### Whole-Repo View

In scope for the future implementation design:

- `shifter/shifter_platform/config/settings.py`
- `shifter/shifter_platform/config/_oidc_settings.py`
- `shifter/shifter_platform/config/urls.py`
- `shifter/shifter_platform/config/env-manifest.json` and
  `config/_env_manifest.py` if settings env bindings change
- `shifter/shifter_platform/risk_register/models.py`
- `shifter/shifter_platform/risk_register/api/authentication.py`
- `shifter/shifter_platform/risk_register/api/permissions.py`
- `shifter/shifter_platform/risk_register/api/serializers.py`
- `shifter/shifter_platform/risk_register/api/views.py`
- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/shared/auth.py`
- `shifter/shifter_platform/shared/errors.py`
- `shifter/shifter_platform/shared/log_sanitize.py`
- Mission Control API views and `mission_control/urls.py`
- CTF API views, `ctf/views/_access.py`, `ctf/views/_parsing.py`, and
  `ctf/urls.py`
- CMS experiment and scenario editor JSON endpoints
- Django admin or the existing platform admin UI for token management
- tests under `tests/risk_register`, `tests/shared`, `tests/mission_control`,
  `tests/ctf`, `tests/cms`, and `tests/config`
- `.importlinter`, ADR docs, and ADR guard checks if boundaries or guardrails
  change

Usually out of scope:

- Terraform, Kubernetes, or deploy workflow changes unless new runtime config or
  secret-delivery paths are introduced.
- Replacing OIDC, Identity Platform, CTF magic links, or Django sessions.
- Converting all JSON APIs to DRF as part of token authentication.
- Redesigning CTF participant/organizer roles or CMS authoring policy.
- Removing legacy risk-register API key compatibility without a separate
  migration/deprecation decision.

## Gotchas And Anti-Patterns

- Do not assume DRF default auth covers `/mission-control/api/...`, `/ctf/api/...`,
  CMS experiments, or scenario-editor endpoints.
- Do not make `risk_register.models.APIKey` the imported platform principal
  across unrelated apps. That leaks an app-local concept into the platform
  boundary.
- Do not add a second token store with different hashing, prefix, expiry,
  revocation, serializer, and audit semantics.
- Do not treat token scopes as object ownership or domain authorization.
  `ctf:event:write` still cannot mutate another organizer's event.
- Do not treat `CTF Organizer` as staff, superuser, Threat Research, or Django
  admin for token management.
- Do not use wildcard scopes by default. If an admin "all scopes" affordance is
  needed, it should expand to the current explicit scope set at creation time or
  be represented by a deliberately reviewed reserved scope.
- Do not log every successful token-authenticated request blindly across the
  whole platform without an explicit volume decision. Creation, revocation,
  authentication failure, and sensitive state changes must be auditable; a
  per-request success audit row can become write amplification once tokens cover
  all APIs.
- Do not update `last_used_at` with an unconditional database write on every
  request if high-frequency automation is expected. Bound or coalesce the write
  while preserving useful operator visibility.
- Do not put raw tokens in admin search fields, audit `new_state`, test
  snapshots, fixtures, changelog snippets, command examples, query strings, or
  browser localStorage.
- Do not accept token creation through GET or without CSRF on session-auth admin
  UI paths.
- Do not let invalid bearer credentials fall through to a logged-in browser
  session on the same request; that creates ambiguous authorization behavior.
- Do not duplicate body parsing, validation, exception mapping, or group-role
  predicates as part of token support.

## Non-Goals

- No implementation in this preflight note.
- No new formal ADR unless implementation changes repo-wide auth, import,
  guardrail, or audit policy beyond the boundaries above.
- No OAuth2 authorization-server or third-party token introspection protocol.
- No JWT bearer-token format unless separately justified; opaque server-stored
  tokens are sufficient for PLAT-102 and easier to revoke.
- No broad public API versioning redesign.
- No weakening of CSRF, OIDC/Identity Platform, CTF magic-link, dev-login, or
  admin bootstrap controls.
