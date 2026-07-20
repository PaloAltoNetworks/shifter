# CTF Bootstrap Credential Hardening Preflight

Issue: GitHub #1665, "CTF temporary participant accounts fall back to a
shared hardcoded bootstrap password".

This note records the architecture boundary for the focused security fix. It
is not an implementation plan. GitHub issue #1665 is the authoritative
contract; no Ground Control requirement is attached.

## Decision Boundary

Bootstrap credential resolution must fail closed at the participant-account
service boundary. The only accepted sources are, in order:

1. the event's explicit `participant_password_override`, already encrypted at
   rest; or
2. an explicitly configured `CTF_DEFAULT_PARTICIPANT_PASSWORD` runtime secret.

If neither source is non-blank, account creation, account attachment,
credential reset/resend, bootstrap-reuse comparison, and organizer reveal must
raise a controlled existing CTF domain error. No repository literal, settings
constant, `getattr` default, model default, migration default, deployment
default, or implicit development value may become an authenticating
credential. Tests may install a clearly synthetic value explicitly through
`override_settings` or a fixture.

This issue should use the fail-closed remediation allowed by #1665. Unique
per-account bootstrap generation is intentionally deferred: the current
manual handoff and organizer reveal workflow depends on a recoverable
event-level credential, while Django correctly stores account passwords only
as one-way hashes. Per-account generation would therefore require a separate
one-time issuance/delivery contract, not a reversible password column hidden
inside this fix.

No new ADR is needed. ADR-008's production security posture, ADR-009's identity
boundary, ADR-018's fail-closed configuration precedent, and the original
isolated-account preflight already own the applicable boundaries. This note
supersedes only that preflight's former acceptance of a public bootstrap
default.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1665 |
| --- | --- | --- |
| Credential resolution | `ctf.services.participant.accounts.effective_bootstrap_password` | Keep one resolver used by create, attach, reset, change-password reuse checks, and organizer reveal. It returns a validated credential or raises; callers must not add fallback chains. |
| Account persistence | Django `User.create_user` / `set_password`; `management.services.configure_temporary_ctf_account` and `set_ctf_password_change_required` | Persist only Django's password hash and the existing origin/force-change markers. No new model, DTO schema, reversible per-account field, or migration is needed. |
| Event secret storage | `CTFEvent.participant_password_override`; `shared.field_encryption.EncryptedStringField`; `FIELD_ENCRYPTION_KEY` | Preserve the existing encrypted event override. CTF must not copy encryption code or import a provider SDK. |
| Password policy | Django `validate_password`, configured `AUTH_PASSWORD_VALIDATORS`, and `PasswordChangeForm` | Apply the canonical validators to every non-empty configured source before use; keep participant-chosen password validation in `PasswordChangeForm`. Do not create a second strength policy. |
| Runtime config | `config._oidc_settings`, `config._runtime_env`, `config._env_manifest`, and generated `config/env-manifest.json` | The platform source is optional because the event source is an alternative, but its unset value must be empty, never a credential. Regenerate the manifest rather than hand-editing it. |
| Runtime secret delivery | Existing app-secret bundle hydration in `entrypoint.sh` / `entrypoint-lib.sh`; AWS/GCP secret-manager references | If deployments use the platform source, carry its value only in the existing secret bundle and process environment. Do not add it to ConfigMaps, public runtime env files, Terraform outputs, or command arguments. |
| Creation workflows | `create_participant_accounts`, `attach_isolated_account`, `invite_participant`, `bulk_import_participants`, event row locks, and Django transactions | Resolve and validate before the first user mutation. Missing/invalid credentials roll back the whole single or bulk operation and never enqueue provisioning. |
| Delivery | `reset_participant_credentials`, `ctf.services.notification._build_ctf_login_url` / `_send_email`, and `shared.email` | Preserve the trusted two-message reset flow and its queued-not-delivered semantics. Escape the password in HTML; never expose it to organizer-authored templates. |
| Session quarantine | `UserProfile.must_change_password`; `CTFAccountBoundaryMiddleware`; `PasswordChangeForm`; Django session auth hashes | A bootstrap-authenticated session may reach only the exact change-password and logout paths until rotation. Do not duplicate this policy in each participant view. |
| Other auth boundaries | `authenticate_ctf_participant`, provider/dev-login marker refusals, `CTFAccountWebSocketBoundary`, and `shared.api_tokens.authentication` | Preserve generic login failure, provider segregation, all-socket denial, and token rejection/revocation for marked accounts. |
| Errors | `CTFValidationError` / `CTFStateError`; HTML form errors; legacy `_json_error`; canonical DRF error handling | Reuse the existing hierarchy and adapters. Use a stable non-sensitive code/message for unavailable credential state; never serialize raw settings, encryption, database, or email exceptions. |
| Rate limits | `shared.rate_limit.consume_fixed_window` and the `launch_rate_limit` cache | Keep both CTF login and organizer reset/delivery budgets. Missing configuration must not bypass or reset either counter. |
| Audit and logs | `shared.audit`, request IDs, and `shared.log_sanitize` | Audit security mutations by internal actor/subject IDs when those paths are touched. Never log or audit the credential, its hash, email body, submitted password, or a failed-login username. |

## Cross-Cutting Security And Runtime Layers

- **Browser and request admission:** existing TLS, `ALLOWED_HOSTS`, CSRF,
  secure cookies, CSP, clickjacking, referrer policy, `never_cache`,
  `sensitive_post_parameters`, and `sensitive_variables` remain authoritative.
  Credential values never enter URLs, redirects, JavaScript, data attributes,
  browser storage, or cacheable responses.
- **Input and policy validation:** `CTFEventForm` continues to validate an event
  override, but the service resolver repeats the authoritative password-policy
  check because settings, tests, scripts, model saves, and existing database
  rows can bypass the form. Blank means unavailable, not a valid password.
- **Authentication:** `authenticate_ctf_participant` retains timing-safe unknown
  user handling and the active-account/live-event/origin checks. Wrong or
  unavailable credentials remain the same generic login failure; the resolver
  must not be called in a way that reveals configured-source presence at the
  public login endpoint.
- **Session authorization:** the login view may establish Django's quarantined
  session so `PasswordChangeForm` can verify the old password. On every later
  request, `CTFAccountBoundaryMiddleware` must allow only
  `/ctf/change-password/` and `/logout/` while `must_change_password=True`;
  CTF HTML and API paths remain unusable. Password reset changes the session
  auth hash and restores the flag atomically, invalidating old sessions.
- **Non-HTTP escape paths:** all marked accounts remain denied by
  `CTFAccountWebSocketBoundary`. `ApiTokenAuthentication` continues to reject
  and revoke any defensive token row owned by a marked account. Provider,
  development, admin, and generic password backends must not bind or authenticate
  the temporary account outside the dedicated CTF path.
- **Persistence and concurrency:** event row locks, nested Django transactions,
  username uniqueness, participant/user constraints, and
  `transaction.on_commit` provisioning remain intact. Credential resolution
  failure occurs before user/profile/participant writes; no partial seat,
  notification, or provisioning task survives.
- **Secret storage and transport:** account passwords remain KDF-only. The event
  override remains encrypted by `EncryptedStringField`; the optional platform
  value remains process-local after existing secret hydration. SMTP and browser
  transport retain existing TLS posture. Plaintext exists only in the bounded
  resolve/hash/reveal/reset/send call chain.
- **Config shape:** `_oidc_settings.py` remains the existing owner; do not add a
  second CTF settings schema. The generated env manifest must show no
  authenticating default. If deployment support for the platform source is
  changed, update the existing app-secret bundle, AWS/GCP render/hydration
  tests, and runtime inventory together; secret values never enter checked-in
  runtime files.
- **OS/process exposure:** no credential in `argv`, shell command strings,
  Terraform plan/output, Kubernetes `ConfigMap`, Job spec literals, worker
  titles, task metadata, `/tmp`, environment dumps, logs, metrics, audit JSON,
  or CI annotations. Secret-manager IDs/references may cross those surfaces;
  values may not.
- **Error envelopes and observability:** organizer HTML receives a bounded form
  error; legacy JSON retains its controlled flat error; DRF retains the shared
  canonical envelope and request ID. Logs may include action, event/participant
  ID, source selected as a low-cardinality label, and outcome—not the value or
  user-submitted credential material.

## Extensibility Seam

The seam is the single service-owned credential resolver/issuer called with the
event. For this fix it resolves an explicit event or platform source and fails
closed. Do not add a strategy enum or provider abstraction pre-emptively.

If a later issue introduces per-account credentials, evolve this seam to accept
the account/reset operation and return a one-time issuance result that the
existing delivery workflow consumes before discarding plaintext. That later
contract must define email-less/manual handoff, batch output, retry semantics,
and non-recoverability; it must not make account passwords decryptable.

## Whole-Repo Boundary

The implementation must consider these existing surfaces together:

- `ctf/services/participant/accounts.py`, `lifecycle.py`, and `bulk_import.py`;
- participant creation/reset adapters in `ctf/views/admin_participant_accounts.py`,
  `ctf/views/admin_people.py`, and `ctf/views/api/participants.py`;
- `ctf/views/participant_auth.py`, `config/middleware.py`,
  `config/websocket_auth.py`, provider/dev authentication backends, and shared
  API-token authentication;
- `ctf/forms.py`, `ctf/models/event.py`, `shared/field_encryption.py`, and
  `management/services.py`;
- `ctf/services/notification.py`, `shared/email.py`, shared rate limiting,
  audit, log sanitization, and existing CTF/DRF error adapters;
- `config/_oidc_settings.py`, `config/_runtime_env.py`,
  `config/_env_manifest.py`, generated `config/env-manifest.json`, app-secret
  hydration, and provider runtime inventory/renderers if secret delivery changes;
- CTF participant account, view, notification, middleware, WebSocket, API-token,
  config, and env-manifest tests; and
- participant/organizer/QA documentation that currently describes a platform
  bootstrap default or reveal/reset behavior.

## Gotchas And Anti-Patterns

- Do not replace the repository literal with another constant, random value at
  settings import, empty password, unusable password that silently creates an
  inaccessible account, or a warning that allows creation to continue.
- Do not require the platform setting at startup while an event override is a
  valid alternative. Fail at the account service boundary, where the event is
  known, unless the product intentionally removes event-level configuration.
- Do not validate only in `CTFEventForm`; direct service calls and persisted
  legacy values bypass it. Do not copy Django's validator rules into CTF code.
- Do not resolve once outside a bulk transaction and then partially create
  accounts. One missing/invalid source fails the entire requested operation.
- Do not let reset mutate the password and only later discover that the source
  is unavailable. Resolve and validate first; password, force-change flag, and
  token revocation remain one transaction.
- Do not let missing-source errors escape adapters as 500s. The reset JSON
  adapter currently handles a narrower exception set than account creation;
  whichever existing CTF error class the resolver uses must be mapped by every
  HTML, legacy JSON, bulk-import, and DRF caller. Participant detail should show
  a controlled unavailable state rather than losing the entire organizer page.
- Do not assume a redirect from the login view is the force-change control.
  Middleware, WebSocket denial, API-token denial, and password-hash invalidation
  are the enforceable boundaries and require direct regression tests.
- Do not return an API redirect containing HTML as a new public contract. The
  forced-change session must remain unable to perform the API operation; any
  future JSON-specific denial should use the existing API envelope.
- Do not interpolate an organizer-configured password unescaped into HTML email,
  expose it through custom templates, log it on delivery failure, or claim the
  fire-and-forget email was delivered.
- Do not introduce a credential repository, encryption wrapper, exception
  hierarchy, validation schema, config parser, rate limiter, audit store,
  scheduler task, or notification workflow for this issue.

## Non-Goals

- No per-account credential generation, one-time secret-download UI, recovery
  code, passwordless/magic-link flow, MFA, provider-auth redesign, or new
  participant identity model.
- No migration or rotation of existing account password hashes, event
  overrides, `FIELD_ENCRYPTION_KEY`, Django sessions, API tokens, or cloud
  secrets. Operators may need an explicit reset for already provisioned accounts;
  silent mass reset is out of scope.
- No redesign of participant creation, range provisioning, scheduler/email
  durability, event ownership, scoring eligibility, retention/anonymization, or
  organizer authorization.
- No removal of the encrypted event override or manual handoff workflow in this
  fail-closed remediation. A product decision to require unique per-account
  issuance belongs in a separate contract.

## Validation Guardrail

A future implementation must prove: no default literal or constant remains;
missing and blank sources fail every creation/attach/reset path without partial
state; each explicit source passes canonical password validation; reset
invalidates old sessions and API tokens; a force-change session cannot use CTF
HTML, API, platform, or WebSocket surfaces; errors and logs contain no secret;
and the generated env manifest is current. Architecture CI remains mandatory
for the touched platform/config/auth surfaces.
