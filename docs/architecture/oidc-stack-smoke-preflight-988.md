# OIDC Stack Smoke Preflight (#988)

Status: pre-implementation guidance

Date: 2026-07-14

Issue: GitHub #988, "test: cover the real OIDC login path in the stack
smoke"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note fixes the verification boundary;
it is not an implementation plan.

## Decision And Scope Boundary

Extend the existing built-image stack smoke with a deterministic, local,
protocol-capable OIDC provider double and replace its direct Django-session
minting shortcut with the resulting callback-established session. Keep the
provider, browser/probe, portal image, Postgres, and existing dependency doubles
on the smoke's private network. The blocking Quality gate must remain hosted,
credential-free, and independent of a live Cognito tenant.

The successful path must begin at the public `/login/` router and traverse the
real first-party topology:

`/login/` -> `mozilla_django_oidc` authorization request -> provider
authorization -> `/oidc/callback/` -> token/JWKS/UserInfo handling ->
`ShifterOIDCBackend` -> user/profile identity binding -> Django login/session ->
an authenticated page.

Only the identity provider is doubled. The smoke must not patch, replace, or
call around `platform_login`, the `mozilla_django_oidc` request/callback views,
`ShifterOIDCBackend`, `management.services`, the user-profile signals, Django's
session middleware/backend, or the built image's real entrypoint. This is the
external-network boundary permitted by ADR-019, not a fake first-party auth
stack.

Keep these concepts separate:

1. The existing #922 session shortcut proves authenticated runtime behavior
   given a session. It does not prove login and must no longer supply the
   session used by the websocket/page checks.
2. The local IdP proves the application-observed OIDC authorization-code flow.
   It does not prove Cognito password, Hosted UI, MFA, availability, or a live
   tenant's current configuration.
3. OIDC/Cognito and GCP Identity Platform are distinct provider adapters under
   ADR-009. Issue #988 targets the OIDC redirect/callback path; do not route it
   through `identity_platform_session` or generalize both flows.
4. User creation, `UserProfile` creation, immutable issuer/subject binding,
   role reconciliation, and browser-session creation are distinct stages. The
   check must prove the expected durable/session outcomes without duplicating
   their implementation.

No new ADR is needed. ADR-009 already owns the provider boundary and verified
identity invariant; ADR-019 already requires real first-party topology with
only the external boundary doubled.

## Architecture Decisions And Guardrails

- Reuse `scripts/stack-smoke/stack_smoke.sh` and the existing `stack-smoke`
  Quality job. Do not build the production image twice, add a provider-specific
  workflow, or recompute changed paths. `deploy.yml`, `_quality.yml`, and
  `.github/quality-path-filters.yaml` already route changes under
  `scripts/stack-smoke/**` to the gate.
- Use a maintained OIDC test provider or fixture that can be configured to the
  production Cognito-shaped contract. Pin its image/artifact immutably. Do not
  implement OAuth/OIDC inside the portal, and do not add provider-test code to
  a production Django app.
- The double must expose the exact endpoint shapes produced by
  `config._oidc_settings`: `/oauth2/authorize`, `/oauth2/token`,
  `/oauth2/userInfo`, and `/.well-known/jwks.json`. Do not weaken or special-case
  production endpoint construction to fit a convenient generic mock.
- The double must enforce the configured client id, client secret,
  authorization-code flow, exact callback URI, and one-time code exchange. It
  must issue an RS256 ID token with a matching `kid`/JWKS, issuer, audience,
  nonce, subject, email, and literal-boolean `email_verified: true`; UserInfo
  must require the access token and return the same subject. An accept-anything
  redirect server would not catch OIDC configuration regressions.
- Start with no matching Django user/profile. The provider may auto-authenticate
  one fixed synthetic user so CI does not automate a password UI, but the app
  must receive that identity only through the authorization response and real
  token/UserInfo calls.
- Preserve the production settings posture: no `TESTING=1`, `DJANGO_DEBUG=true`,
  `ENVIRONMENT=development`, `/dev-login/`, direct `SessionStore`,
  `force_login`, or `login()` call from the harness. Keep secure-cookie and HTTPS
  semantics. A private-network probe may map logical HTTPS URLs to local
  transport, but it must preserve the logical Host, forwarded scheme, redirect
  URI, cookie scope, and Secure-cookie behavior rather than disabling the
  security settings.
- Reuse the callback-established session for the existing websocket handshake
  and authenticated page/static checks. One browser session should prove the
  whole chain; do not retain a second directly minted session as a fallback.
- Verify provisioning by reading durable outcomes after the callback: exactly
  one new Django user, exactly one `UserProfile`, and the expected opaque
  `issuer`/subject binding in the incumbent `issuer` + legacy-named
  `cognito_sub` fields. Do not write setup rows or add a smoke-only model,
  repository, DTO, migration, or provisioning endpoint.
- Verify session establishment through observable behavior: the callback sets
  a Django session, that session names the configured
  `ShifterOIDCBackend`, and a subsequent protected request is authenticated as
  the newly provisioned user. A 302 alone, a session-table row alone, or a user
  row alone is insufficient.
- Keep every provider wait, redirect chain, token request, and assertion
  bounded. Cleanup must remain deterministic and must preserve the original
  failure while removing the provider, cookie material, and network resources.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #988 |
| --- | --- | --- |
| Built-image gate | `scripts/stack-smoke/stack_smoke.sh`, its `README.md`, `.github/workflows/_quality.yml` `stack-smoke`, `deploy.yml` path signals | Extend one harness/job and consume its existing parameter seam; no duplicate job or router. |
| Public login routing | `config.views.platform_login`, `config.urls`, `mozilla_django_oidc.urls` | Begin at `/login/` and use the library's real request/callback views. |
| OIDC protocol/config | `config._oidc_settings`, `mozilla_django_oidc`, `config.oidc.ShifterOIDCBackend` | Preserve state/nonce, code exchange, JWKS/signature, exact issuer/audience/azp, UserInfo subject parity, and callback/session behavior. |
| Runtime config validation | `config._runtime_env.required_runtime_env`, `config._env_manifest`, `config/env-manifest.json` | Use existing `AUTH_PROVIDER`/`OIDC_*`/Django env names. Smoke-only harness parameters are not new application settings. |
| Runtime secret shape | `entrypoint.sh`; Cognito secret JSON in `platform/terraform/modules/portal/cognito/main.tf`; AWS portal deploy/user-data wiring | Use synthetic local values with the same `client_id`, `client_secret`, `domain`, and `issuer_url` meanings; do not call a secret manager. |
| Verified identity | `shared.verified_identity.VerifiedIdentity` and `VerifiedIdentityError` | Do not add a test claims DTO or duplicate strict claim validation. |
| Account persistence | `management.models.UserProfile`, `management.apps` post-save handlers, `management.services.resolve_user_by_provider_identity` / `bind_provider_identity` | Observe the real atomic bind-once path; do not write profile fields from the harness. |
| Privilege/role reconciliation | `config.bootstrap_admin`, `config.cognito_groups`, `config.organizer_authority`, `config.user_type_sync` | Let the real callback invoke them after verified binding. Keep the synthetic identity non-privileged unless a separate assertion requires a fixed provider group. |
| Audit and logs | `shared.audit`, `risk_register.models.AuditLog`, `config._logging_config`, `config.logging.ECSFormatter`, `shared.log_sanitize` | Preserve real auth audit behavior and sanitized operational logs; no smoke event schema or exception taxonomy. |
| Browser/session security | Django Security/Session/CSRF/Authentication middleware, `SECURE_PROXY_SSL_HEADER`, secure cookie settings | Exercise the normal middleware/session path and logical HTTPS semantics. |
| Existing regression tests | `tests/mission_control/test_oidc.py`, `tests/config/test_identity_binding_invariant.py`, `tests/management/test_apps.py`, `tests/management/test_services.py`, `tests/platform/test_stack_smoke_job.py` | Keep focused source tests for negative policy and atomicity; add only structural harness protection needed to prevent return of the direct-session shortcut. |
| Deployed Cognito client contract | `platform/terraform/modules/portal/cognito/main.tf`, environment portal roots, rotation tests | Keep code flow, scopes, callback `/oidc/callback/`, and secret-bundle fields aligned. Local IdP evidence must not be claimed as proof of live Terraform/provider state. |

## Cross-Cutting Layers The Design Must Pass

### Security and validation

1. **Browser/request admission:** `/login/` must route to the library init view;
   `ALLOWED_HOSTS`, `SecurityMiddleware`, session middleware, and the logical
   HTTPS/secure-cookie posture remain active. The probe behaves like a browser
   with a cookie jar; it is not allowed to inject Django session keys.
2. **Authorization response:** `mozilla_django_oidc` owns generated state,
   nonce, redirect URI, and callback validation. The provider echoes the real
   state and binds its signed token to the real nonce; no recorded or
   precomputed callback query is accepted.
3. **Provider/client validation:** the local provider rejects the wrong client,
   secret, flow, scope/callback shape, reused code, or bearer token. This is the
   local proof that `OIDC_AUTH_DOMAIN`, `OIDC_RP_CLIENT_ID`, and
   `OIDC_RP_CLIENT_SECRET` are actually consumed.
4. **Token/claim validation:** the real backend passes RS256 signature/JWKS and
   exact issuer/audience/azp checks, then requires ID-token/UserInfo subject
   parity plus non-empty email/subject and literal-true `email_verified` before
   lookup or mutation. Do not relax `ShifterOIDCBackend` for the double.
5. **Persistence/policy:** real ORM creation, profile signals/services,
   row-locked immutable identity binding, strict audit for the security
   mutation, bootstrap policy, provider-group reconciliation, and CTF user-type
   sync run in their existing order. The smoke observes outcomes only.
6. **Session establishment:** Django's callback/login machinery writes the
   normal database-backed session and secure cookie, and
   `AuthenticationMiddleware` resolves it on a later protected request.
7. **Configuration shapes:** the portal continues to fail closed through
   `required_runtime_env`, `require_environment`, `resolve_cloud_provider`,
   allowed-host validation, DB/field-encryption/email/Redis settings, and the
   existing OIDC env bindings. If an application env binding is introduced
   despite this guidance, update the env extractor/manifest and every relevant
   runtime renderer/inventory; do not hand-maintain a smoke-only setting.
8. **Secret and OS exposure:** use only synthetic provider credentials. Auth
   codes, state, nonce, ID/access tokens, session cookies, and cookie-jar
   contents must not appear in process argv, environment dumps, GitHub
   annotations, shell tracing, test snapshots, or raw failure logs. The current
   `--session` helper interface is an expected touchpoint: pass session material
   in memory/stdin or through a mode-0600 temporary file whose path, not value,
   is the argument, then delete it in the trap.
9. **Error envelopes and diagnostics:** keep the library's generic callback
   failure and the backend's bounded exception-type audit behavior. Harness
   failures may name the phase and status/category, never provider response
   bodies or secret-bearing URLs. Redact query values such as `code`, `state`,
   and token/cookie fields before emitting bounded portal/provider log tails.

### Maintainability

The implementation must build on the incumbents in the table above. In
particular, do not add an auth service, provider-neutral callback controller,
claims schema, validation helper, exception hierarchy, audit model, user/profile
repository, or workflow parser. A test-only provider configuration and browser
probe belong with `scripts/stack-smoke`; production application packages should
change only if the smoke exposes a real defect.

The existing source-tree OIDC tests remain valuable for negative issuer,
audience, `email_verified`, binding-drift, atomicity, and audit cases. They do
not substitute for this built-image flow, and the new smoke does not need to
recreate their failure matrix over HTTP.

### Extensibility

The next reasonable variation is another OIDC fixture version or synthetic
claim set, not a second workflow. Extend the existing smoke parameter seam with
one provider scenario: immutable provider image/artifact, service address,
client id/secret input, registered callback, issuer, and fixed user claims.
Keep the login probe parameterized by logical portal origin and expected
identity. A provider swap or an added non-privileged claim should be a parameter
change; it must not require editing production `_oidc_settings` or copying the
stack harness.

Identity Platform browser-token exchange, live Cognito canaries, multiple
providers per runtime, and account linking are different seams and must not be
pre-designed into this fixture.

### Whole-Repository Scope

Expected implementation surfaces are:

- `scripts/stack-smoke/stack_smoke.sh`, `README.md`, a local IdP fixture/config,
  and a bounded login/browser probe;
- `scripts/stack-smoke/ws_handshake.py` and `page_smoke.py` for non-argv session
  handoff and reuse of the callback-created session;
- `shifter/shifter_platform/tests/platform/test_stack_smoke_job.py` to pin the
  real-login/no-direct-session harness contract;
- `docs/architecture/built-image-stack-smoke-preflight-922.md` only to remove
  obsolete wording once the shortcut is replaced.

These are contract incumbents to inspect and normally leave unchanged:

- `config/urls.py`, `views.py`, `_oidc_settings.py`, `_runtime_env.py`,
  `oidc.py`, `bootstrap_admin.py`, `cognito_groups.py`,
  `organizer_authority.py`, and `user_type_sync.py`;
- `shared/verified_identity.py`, `shared/audit.py`, logging/sanitization, and
  Django middleware/settings;
- `management/apps.py`, `models.py`, `services.py`, existing migrations, and
  database-backed sessions;
- `entrypoint.sh`, the Cognito Terraform module/environment callback wiring,
  client-secret rotation, and AWS portal runtime wiring;
- `.github/workflows/_quality.yml`, `deploy.yml`, and
  `.github/quality-path-filters.yaml`.

If the smoke exposes a real application or deployed-client contract defect,
fix it in its canonical owner and add focused regression coverage there. Do not
work around it in the provider double.

## Gotchas And Anti-Patterns

- Do not call backend `create_user`, `authenticate`, or `login()` directly and
  call that end-to-end. Do not use `SessionStore`, `force_login`, a database
  session insert, `/dev-login/`, or a pre-baked session cookie.
- Do not replay a recorded callback/token response. State, nonce,
  authorization-code single use, token signature/JWKS, and session cookies are
  per-run security state; a recording bypasses the exact regressions at issue.
- Do not make the local provider accept arbitrary client ids, secrets,
  redirect URIs, unsigned/HS256 tokens, missing nonce, mismatched subjects, or
  truthy string `email_verified` values.
- Do not weaken HTTPS redirect, secure cookies, issuer/audience checks,
  callback/state/nonce checks, profile binding, audit strictness, or
  first-party middleware to make local networking easier.
- Do not confuse the Cognito authorization domain with the issuer/JWKS base.
  `_oidc_settings` intentionally has both; the fixture must model that contract
  even when both resolve to one local service.
- Do not assert only final dashboard status. Capture enough bounded phase
  evidence to distinguish login router, provider authorization, callback,
  provisioning, and authenticated-session failure without logging artifacts.
- Do not assert only that a user/profile exists; stale setup data is a false
  pass. Prove absence before the flow, creation by the callback, immutable
  binding values afterward, and authentication with the returned cookie.
- Do not dump `docker inspect`, the environment, cookie jars, full callback
  URLs, HTTP traces, or unredacted web/IdP access logs on failure. Gunicorn
  request lines may contain callback query parameters.
- Do not add live cloud credentials, GitHub OIDC permissions, repository
  secrets, a self-hosted runner, or a public callback endpoint to the blocking
  Quality job.
- Do not claim the local double validates live Cognito availability, password
  or MFA policy, Terraform apply state, secret rotation convergence, DNS, TLS,
  or production callback registration. Those require a separately authorized
  post-deploy/live-provider canary.
- Do not duplicate the Quality job, path classifier, application auth config,
  verified-identity contract, profile schema, audit schema, or exception
  hierarchy.

## Non-Goals And Implementation Boundaries

- No issue implementation in this preflight change.
- No redesign of OIDC/Cognito, Identity Platform, Django sessions, bootstrap
  admin policy, organizer authority, CTF account auth, logout, audit, or browser
  security.
- No production schema or migration, provider abstraction, controller/DTO,
  persistence repository, health endpoint, or workflow framework.
- No live Cognito user/password/MFA automation and no provider-side credential
  lifecycle test in the hosted Quality job.
- No coverage of GCP `identity_platform_session`; it is not a redirect/callback
  OIDC flow and has its own verified-token contract.
- No guarantee about deployed Cognito drift from local evidence alone. Preserve
  the Terraform/secret/runtime contract and use a separately scoped live check
  if operational verification of a deployed tenant is later required.
