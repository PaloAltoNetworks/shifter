# Isolated Temporary CTF Participant Accounts Preflight (#1206)

Status: pre-implementation guidance

Date: 2026-07-12

Issue: GitHub #1206, "Replace CTF magic-link login with isolated, temporary
username/password participant accounts"

This issue is requirement-free. Its title, body, and acceptance criteria are
the shipping contract. This note fixes the repository-wide identity and
authorization boundaries before implementation; it is not an implementation
plan.

> **Security supersession (#1665):** the public bootstrap-password fallback
> accepted by the original version of this note is no longer permitted. See
> `docs/architecture/ctf-bootstrap-credential-hardening-preflight-1665.md` for
> the fail-closed credential-source and session-quarantine guardrails. All other
> account-isolation boundaries in this note remain in force.
>
> **Workflow supersession (#1924):** persistent reveal, deployment-wide
> bootstrap selection, reset-to-shared, and password-email delivery are no
> longer permitted. See
> `docs/architecture/participant-password-one-time-reset-preflight-1924.md`.
> The account-origin, participant-isolation, forced-change, provider
> segregation, and cleanup boundaries below remain in force.

## Scope Boundary And Invariants

This is a replacement of the participant authentication and account lifecycle,
not a hardening of magic links and not another platform identity provider.
Keep these concepts separate:

1. **Account origin** is the immutable fact that a Django user was created as a
   temporary, local CTF account. It is not a role claim.
2. **Role** is the `CTF Participant` group plus
   `UserProfile.user_type="ctf_participant"`. Role state remains useful for
   navigation and ordinary permission checks, but is not strong enough to prove
   account origin because provider/dev flows can synchronize it.
3. **Participation** is the event-scoped `CTFParticipant` row. It owns display
   name, optional delivery email, team/bracket/scoring state, range reference,
   and participant status.
4. **Credential state** is Django's one-way password hash plus
   `UserProfile.must_change_password`. It is not participant profile state and
   must never be copied into the participant row, audit state, or notification
   records.
5. **Delivery state** is whether an optional email was queued and when. Email
   is not an identity key and must never select or link a Django user.

The non-negotiable identity invariant is:

> A CTF login admits only a fresh Django user carrying the immutable temporary
> CTF-account marker and its one active event participation. Provider/platform
> login rejects that marker before binding, role synchronization, elevation, or
> session creation. No email lookup may connect the two account classes.

The marker is deny-authoritative: even if an administrator accidentally adds a
platform group or staff flag, the account remains confined to CTF participant
surfaces and is rejected by platform authentication.

## Architecture Decisions And Guardrails

### Identity And Persistence

- Add a durable `UserProfile` origin marker such as `is_ctf_account`, separate
  from `user_type`. The marker starts false, is set only while creating a fresh
  local CTF account, never transitions back to false, and remains true on an
  anonymized tombstone. Add `must_change_password` beside it.
- Constrain a marked profile, at the database level where the profile table can
  express it, to `user_type="ctf_participant"`, empty `issuer`, and null
  `cognito_sub`. Cross-table facts (`is_staff`, `is_superuser`, and group
  membership) stay enforced by the account service and the deny-authoritative
  request boundary.
- `auth_user.username` is the only login handle and the only stored username.
  Do not add `CTFParticipant.username`, `handle`, or another unique copy. The
  participant's existing `name` remains a display/scoring name, not an auth
  identifier. Organizer rename row-locks and changes `User.username` through
  the participant account service.
- Generated and organizer-supplied handles use one CTF-owned canonical
  normalizer/validator. Restrict them to a lowercase, email-disjoint namespace
  (for example `range-` plus an eight-hex CSPRNG suffix), pass the value through
  Django's `User.username` field validation, and rely on the existing global
  database uniqueness constraint. Catch `IntegrityError` and retry generated
  collisions a bounded number of times; pre-checks alone are racy.
- Add a conditional uniqueness constraint so one non-deleted participant user
  cannot back more than one active `CTFParticipant`. A temporary account is one
  seat in one event; the old multi-event, email-linked user semantics must not
  survive through the new model.
- Keep delivery email only on `CTFParticipant`; keep `User.email` and name fields
  empty for CTF accounts. Make participant email optional using one empty value
  (`blank=True`, `default=""`) rather than introducing both null and empty-string
  representations. Remove email uniqueness: duplicate or absent delivery
  addresses are legitimate and never imply shared identity.
- Integrations that require a non-empty session identity must not reinterpret
  delivery email as the login key or backfill `User.email`. Preserve ordinary
  account behavior while admitting email-less CTF accounts with Django's
  canonical handle fallback (`user.email or user.get_username()`), and name
  downstream parameters for an identity/username rather than falsely promising
  an email address.
- Do not mark existing linked users as CTF accounts. Legacy rows may point at
  organizers, staff, or ordinary provider users—the exact takeover condition
  being removed. Cutover must either create/relink fresh temporary accounts or
  reject deployment while a non-terminal event needs an explicit operational
  migration. It must not silently break existing range ownership: CTF, CMS, and
  engine records are keyed by the owning user id.

### Password And Secret Handling

- Call `User.set_password()` / `create_user(password=...)`; the authenticating
  credential stays only as Django's password KDF hash. Never add a reversible
  per-account password field.
- The effective bootstrap password is an explicit event override or an
  explicitly configured Django setting, resolved by one service accessor. If
  neither is present, account creation/reset/reveal fails closed. No repository,
  settings, deployment, or model default may become an authenticating
  credential (#1665).
- An event override must be recoverable for manual reveal and reset/resend, so
  store only that shared event bootstrap value with the existing
  `FIELD_ENCRYPTION_KEY` field-encryption posture. The generic encryption
  primitive currently under `cms.credential_encryption` must be reused or
  narrowly lifted to `shared`; CTF must not import CMS internals or copy Fernet
  code, prefixes, key handling, or exception behavior.
- A "resend credentials" action cannot resend a participant's current password
  after first-login change—Django correctly cannot recover it. Define the
  action as **reset to the event's current bootstrap password, set
  `must_change_password=True`, invalidate existing sessions, then queue the two
  messages**. Label it as a reset in UI, logs, audit, and confirmation text.
- Use Django's configured password validators for every explicit bootstrap
  source and new participant-chosen passwords. The change-password service must
  also reject reusing the current bootstrap password; otherwise first-login
  change can clear the flag without changing the known credential.
- Login, password override, reset, reveal, and change views are CSRF-protected,
  HTTPS-only under existing deployment posture, `no-store`, and annotated with
  Django `sensitive_post_parameters` / `sensitive_variables` so exception
  reports do not capture credentials. Passwords must not enter messages, form
  errors, redirects, query strings, HTML data attributes, JavaScript, browser
  storage, logs, metrics, audit JSON, task metadata, or tests/snapshots.

### Login, Session, And Provider Segregation

- The dedicated CTF login POST uses Django `ModelBackend`, then applies all CTF
  gates before `login()`: durable marker, active user, no staff/superuser or
  non-participant groups, exactly one non-deleted/non-disqualified linked
  participant, and an in-window event whose status is `active` or `paused` and
  whose wall-clock interval is `event_start <= now < event_end`.
- Unknown username, wrong password, unmarked platform user, privilege drift,
  disqualification, deleted participation, and inactive/ended event return the
  same generic authentication failure. Do not reveal which check failed.
- Successful first login goes only to the CTF change-password page. Until
  `must_change_password` is cleared, the account may reach only change-password
  and logout. `PasswordChangeForm`/Django password validation remain the
  canonical shape and policy checks; update the session auth hash only after
  the password and flag commit together.
- Add only the dedicated CTF login and change-password paths to
  `OIDC_EXEMPT_URLS`; remove both `/ctf/register/` entries. Exemption bypasses
  provider session refresh, not CSRF, host validation, TLS, CSP, or the CTF
  account policy gate.
- Both `ShifterOIDCBackend` and `IdentityPlatformBackend` must reject a marked
  CTF account before provider binding, email persistence, bootstrap elevation,
  provider group/user-type synchronization, or session creation. Keep their
  existing verified issuer/subject/email/MFA gates intact. The development
  login and Django admin paths must also fail safe if a submitted username
  resolves to a marked account.
- CTF accounts never need platform API tokens. Reject/revoke a token owned by a
  marked CTF account at the shared API-token authentication/lifecycle boundary;
  otherwise a bearer request can bypass session middleware. Purge/reset also
  revokes any defensive legacy token rows without exposing raw tokens.
- The CTF login intentionally does not invoke provider MFA. It creates the same
  secure Django session used elsewhere, rotates the session key, and relies on
  password-change session-hash behavior to invalidate older sessions.

### Authorization Boundary

- Add one CTF-account HTTP policy boundary after Django authentication. A
  marked account may reach the participant portion of `/ctf/`, the canonical
  participant CTF API under `/api/v1/ctf/`, change-password, logout, and the
  exact `/api/v1/mission-control/guacamole/` broker prefix needed to open its
  own ready range (#1740); all other HTTP surfaces return a fixed 403. The
  Guacamole exception is admission only: the live-participant and forced-
  password-change gates still run first, and Mission Control's session/CSRF,
  actor/scope, request-shape, ready-range ownership, declared-channel, and
  owner-scoped bootstrap-delivery checks remain authoritative. In particular,
  `/api/v1/mission-control/ngfw/`, `range/`, `ranges/`, `credentials/`,
  `upload/`, `agents/`, and `scenarios/` remain outside the exception. Existing
  CTF organizer/participant decorators and DRF permissions still decide which
  operations inside the CTF namespace are valid. Navigation hiding is not
  enforcement (ADR-013).
- The marker check must win over `is_staff`, `is_superuser`, `Threat Research`,
  `CTF Organizer`, or any other accidental group. Evolve
  `shared.auth.is_ctf_participant_only` (or add one clearly named marker
  predicate and make the old helper consume it); do not leave group-only and
  marker-based definitions of "CTF-only" in parallel.
- Deconflate scoring eligibility from live authentication. Existing
  `eligible_participant_q()` intentionally includes completed participants for
  historical leaderboards. A separate canonical live-access predicate must add
  marker, event status/time, deletion, and force-change checks. Do not change
  scoreboard history merely to make login expire.
- HTTP middleware does not cover Channels. Marked CTF accounts must be denied at
  the ASGI WebSocket boundary (permission close code) for Mission Control
  terminal/status and shared notification sockets unless a future explicitly
  participant-owned socket is added. Do not repeat ad hoc checks in every
  consumer.
- Keep defense-in-depth checks at CTF view/DRF and service boundaries. The
  global account boundary prevents cross-surface escape; it does not grant
  event ownership, challenge access, range access, or API scope.

### Creation, Provisioning, And Concurrency

- Single, CSV, and generated-N creation must converge on one participant-account
  creation service. It creates a fresh user unconditionally; no
  `email__iexact`, username-by-email, provider subject, or `get_or_create` lookup
  is permitted.
- Preserve the existing event-row lock and `max_participants` capacity check
  from `invite_participant` / `bulk_import_participants`. Validate positive N
  and apply a bounded server-side batch maximum when an event has no explicit
  maximum. Form/CSV checks improve errors, but service validation plus database
  constraints remain authoritative.
- Account, profile marker, exact group set, participant link, bootstrap password
  hash, force-change flag, and provisioning task enqueue are one database
  transaction. Roll back the whole seat if a security mutation or strict audit
  fails.
- Do not provision cloud resources in the organizer request or account-creation
  transaction. Enqueue/coalesce the existing
  `ctf.services.range.request_event_provisioning()` / `CTFScheduledTask`
  workflow; it already owns background pacing, retry, participant locking,
  heartbeat, progress, and the CMS bridge. Do not add a second batch loop or
  call CMS/engine directly.

### Delivery And Audit

- Keep one login URL builder based on `SITE_URL` and `reverse()`, but remove the
  obsolete registration/token name. The URL contains no credential.
- Optional email delivery queues exactly two messages: first login URL plus
  username, then password alone. Reuse `shared.email` and the existing CTF
  notification service. Continue to describe asynchronous results as queued,
  not delivered; the current thread-backed sender has no durable delivery
  acknowledgement and manual handout is the fallback.
- Organizer-authored email templates continue through
  `ctf.services.email_template`'s flat scalar allowlist. A username placeholder
  is safe to add to the URL/username message. Never expose a password
  placeholder to organizer-authored templates; the password message must use a
  trusted static template.
- Reuse `risk_register.services` and `AuditLog`. Username rename, account
  creation/reset, account disable/anonymize, and privilege-invariant repair are
  security mutations. Rename must audit old/new username and organizer/request
  attribution inside the same transaction with `strict=True`; no audit state
  may contain a password, password hash, event override, email body, session id,
  or delivery address unless an existing privacy policy explicitly requires it.
- Auth success/failure uses `audit_auth_event` with fixed low-cardinality reasons
  and trusted `get_client_ip()` attribution. Failed login must not record the
  submitted username/password. Operational logs use request id, internal user or
  participant ids where necessary, and `safe_log_value` / fingerprints—not
  credentials or rendered messages.

### Temporariness And Cutoff

- Login denial is synchronous with `event_end`, not dependent on scheduler
  health. Event completion, cancellation, participant delete, and
  disqualification also disable the user and set an unusable password so
  existing Django sessions fail their auth-hash/active-user checks.
- Reuse `CTFScheduledTask` / `run_ctf_scheduler` for durable post-event account
  anonymization. Use a distinct validated setting
  `CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS` (recommended default: 24); do not
  reuse range `cleanup_delay_hours`, because cloud teardown timing and identity
  retention are different policies. Event-end rescheduling must move both the
  cutoff and the pending purge task.
- Prefer anonymization/tombstoning over unconditional `User.delete()`. User
  deletion cascades CMS and engine ownership records and can erase range history
  before teardown. The tombstone keeps the user id and immutable CTF marker but
  clears username to a unique non-login tombstone, email/names, groups, provider
  fields, active-event pointer, usable password, and any participant delivery
  email; it sets `is_active=False`, `deleted_at`, and `anonymized_at`.
  Participant display/scoring history remains on `CTFParticipant.name`.
- Delete/disqualify anonymizes immediately after applying the disable boundary;
  normal event completion disables immediately and anonymizes after retention.
  The operation is idempotent and auditable so scheduler retries are safe.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1206 |
| --- | --- | --- |
| User/profile persistence | Django `User`; `management.models.UserProfile`; `management.services` | Add origin/force-change state here and expose mutations through `management.services`; CTF must not import the management model. |
| Provider identity | `shared.verified_identity`, `resolve_user_by_provider_identity`, `bind_provider_identity`, `config.oidc`, `config.identity_platform` | Preserve issuer/subject binding, verified email, corporate allowlist, MFA, and strict audit; add an early CTF-marker refusal. |
| Role policy | `shared.auth`, `config.user_type_sync`, `ctf.bridges.get_user_role` | Marker/origin is distinct from mutable role. Do not create another group vocabulary or let provider sync mutate account origin. |
| Participant access | `ctf.views._access`, `ctf.services.participant.queries` | Keep decorators and event-scoped lookup; add one live-account predicate rather than stretching scoring eligibility. |
| Participant lifecycle | `ctf.services.participant` facade and existing lifecycle/bulk-import split | Replace email-linked auto-registration with one fresh-account primitive reused by single, CSV, and N-account paths. |
| Capacity/concurrency | Event `select_for_update()` checks, Django transactions, global username unique constraint | Keep capacity and creation serialized; enforce collisions and one-seat-per-account in the database. |
| Provisioning | `request_event_provisioning`, `CTFScheduledTask`, `run_ctf_scheduler`, `ctf.services.range`, `ctf.bridges` | Enqueue the existing background flow; do not add cloud calls, sleeps, or a second workflow to creation views. |
| Password policy | Django `ModelBackend`, `set_password`, `PasswordChangeForm`, `AUTH_PASSWORD_VALIDATORS`, session auth hashes | Keep authentication/KDF/change validation canonical; CTF policy only adds marker/event/force-change gates. |
| Secret encryption | `FIELD_ENCRYPTION_KEY`, generic behavior in `cms.credential_encryption` | Reuse/lift the generic encrypted-field primitive through `shared`; never copy it or import CMS internals from CTF. |
| Rate limiting | Atomic fixed-window counter in `mission_control.api.rate_limit`; shared Redis AUTH/TLS/CA posture in `config._redis` | Lift only the generic counter/cache builder to `shared`; keep launch policy in Mission Control and add CTF login policy with a distinct key namespace/cache alias. Do not use process-local invite limiting in production. |
| Email | `ctf.services.notification`, `ctf.services.email_template`, `shared.email`, `SITE_URL` | One tokenless login URL; two messages; password only in trusted template; queue semantics remain explicit. |
| Errors | `CTFValidationError`/`CTFPermissionError`, `_json_error`, `shared.errors`, `shared.api.errors` | Use existing HTML/legacy/canonical envelopes with fixed auth failures; do not add an auth-specific exception hierarchy or serialize raw exceptions. |
| Audit/logging | `risk_register.services`, `AuditLog`, `get_client_ip`, request ids, `shared.log_sanitize` | Strict audit for identity mutations; no secrets or raw submitted identifiers in failure events. |
| Browser security | CSRF middleware, global CSP/referrer/permissions policy (ADR-036), secure cookies/TLS settings | CTF exemption is provider-only; login/change/reveal responses remain CSRF-protected, no-store, and CSP-compliant. |
| Tests | Existing CTF auth/lifecycle/notification/range suites, provider identity invariant tests, API permission/error tests, ADR-019 | Exercise real first-party flows and database constraints; patch only SMTP/provider/cache/network/framework boundaries allowed by ADR-019. |

## Cross-Cutting Security And Runtime Layers

The intended design must pass every layer below:

- **Edge/browser admission:** existing ingress TLS, `ALLOWED_HOSTS`, secure
  cookies, CSRF, global CSP, clickjacking, referrer, and permissions headers
  remain unchanged. Login/change-password are ordinary same-origin forms; there
  is no `csrf_exempt`, cross-origin credential API, inline credential script, or
  new external browser origin.
- **Request shape:** Django forms bound input size/type; generated-N is a bounded
  positive integer; optional email uses `EmailField`; username goes through one
  lowercase CTF validator plus the Django username field; password changes and
  overrides use configured password validators. Services repeat business
  invariants; database constraints close concurrency races.
- **Authentication:** `ModelBackend` proves username/password, then the immutable
  marker, exact account posture, participant state, event status/time, lockout,
  and force-change policies decide whether a CTF session may exist. Provider
  backends independently keep verified token/email/MFA/binding validation and
  reject the marker.
- **Authorization:** CTF account HTTP/ASGI boundaries deny all non-participant
  surfaces. CTF decorators, DRF permissions/scopes, service ownership checks,
  challenge availability, and range ownership still run inside the allowed
  namespace. A rate-limit pass or UI link never grants access.
- **Persistence:** `CTFBaseModel.full_clean`, Django auth constraints, profile
  checks, conditional participant-user uniqueness, transactions, event/user row
  locks, scheduler task claiming, and idempotent purge semantics must all pass.
  No external email/cloud call occurs while holding account-creation locks.
- **Secret storage and transport:** per-account password is KDF-only; only the
  shared event bootstrap override is reversibly encrypted with the existing
  key. TLS carries browser/SMTP traffic. Password plaintext exists only in the
  bounded create/reset/render/send call chain and is never persisted elsewhere.
- **Config shape:** remove `MAGIC_LINK_*` from `_oidc_settings.__all__`, settings,
  tests, and generated env manifest. Add validated non-secret policy settings in
  one settings module and regenerate `config/env-manifest.json` if they are
  environment-bound. Any production override must be wired through both AWS
  and GCP runtime contracts; do not claim an env knob that no deploy can pass.
- **OS/process exposure:** no password or delivery payload in process argv,
  management-command options, shell history, `/tmp`, heartbeat files, ConfigMaps,
  Terraform outputs/state, Kubernetes values, Docker command strings, worker
  titles, or environment dumps. Scheduler metadata contains ids, timing, source,
  and idempotence only.
- **Error envelopes/reporting:** login uses one generic failure; lockout/backend
  outage uses bounded fixed text and retry guidance; CTF APIs retain legacy flat
  and canonical DRF envelopes; provider/API errors keep their existing classified
  messages. Raw database, cache, provider, encryption, SMTP, or validation
  exceptions stay server-side and are sanitized.
- **Observability:** useful dimensions are outcome, auth path, event/task status,
  batch counts, reset/rename/purge action, and bounded wait. Password, hash,
  username submitted on failure, email address, IP, body, headers, cookies, and
  rendered messages are not metric dimensions or log payloads. Durable audit
  carries internal actor/subject ids and request attribution.
- **Runtime workers:** reuse the deployed CTF scheduler and its heartbeat/stale
  recovery. If task types or scheduler timing change, local Compose, AWS/GCP
  scheduler startup, health, and stack-smoke invariants must remain valid.

## Rate-Limit And Extensibility Seams

The next reasonable variations are a different handle prefix/entropy, per-event
password policy, a different retention period, and a future participant-owned
WebSocket. Preserve these seams:

- a pure handle generator plus one validator/normalizer, parameterized by prefix
  and suffix entropy, with database uniqueness authoritative;
- one effective-bootstrap-password accessor (`event override -> explicitly
  configured platform source -> controlled failure`) used by create, reveal,
  reset, and email—never four fallback chains;
- one CTF login policy mapping for per-account and source budgets/lock windows,
  backed by the shared atomic Redis counter with distinct keys;
- one live-account/access predicate shared by login, participant decorators, and
  CTF DRF permission, separate from scoring predicates;
- one allowlist/prefix policy for marked-account HTTP and ASGI surfaces, so a
  future participant route/socket is added once with an explicit test;
- one retention setting and scheduler-owned purge operation, distinct from range
  cleanup timing;
- one account lifecycle service with create, rename, reset, disable, and
  anonymize operations behind the participant service facade.

## Gotchas And Anti-Patterns

- Do not add a participant username column. Dual writes will drift during rename
  and create two uniqueness/validation contracts.
- Do not treat `user_type`, group membership, absence of provider subject,
  email domain, username prefix, or `is_staff=False` as the durable marker.
- Do not use `get_or_create`, `email__iexact`, provider subject, or delivery
  email for participant user selection. Fresh user creation is unconditional.
- Do not copy delivery email into `User.email`; provider fallbacks and dev tools
  already use user email/username for account resolution.
- Do not make optional email both null and blank, and do not replace email
  uniqueness with a duplicate participant-handle field.
- Do not put the event password in `range_config`, notification body rows,
  custom email-template context, task metadata, Django messages, audit state,
  exception details, or JSON responses.
- Do not call a reset "resend" without saying it invalidates the participant's
  current password and sessions.
- Do not use the default `LocMemCache` for production login lockout, import the
  private Mission Control throttle from CTF, or create a second Redis TLS/auth
  parser. A many-worker deployment makes process-local counters ineffective.
- Do not return different login errors for platform users, CTF users, ended
  events, disqualification, nonexistent names, or wrong passwords.
- Do not rely on sidebar hiding, `is_ctf_participant_only`'s current negative
  Launch Range check, or scattered MC decorators for the all-surfaces 403
  criterion. HTTP, canonical API, token, admin, dev-auth, and WebSocket paths all
  need the marker-aware boundary.
- Do not reuse `eligible_participant_q()` as the complete login predicate; its
  completed status is intentional leaderboard history behavior.
- Do not add provisioning calls to the batch view or database transaction. The
  existing scheduler is the canonical background workflow.
- Do not hard-delete users before range teardown/history decisions. CMS and
  engine user FKs cascade; anonymize while preserving the owning user id.
- Do not attach cleanup only to the scheduler's event-end handler. Manual
  complete, cancel, delete, force-delete, disqualify, and wall-clock expiry must
  converge on the same disable/anonymize policy. `start_event`/`end_event` and
  `activate_event`/`complete_event` are overlapping lifecycle APIs; do not add a
  second account-cleanup branch to the dead/legacy pair—delegate or retire it.
- Do not migrate legacy linked rows by flipping their profiles to CTF-only.
  That can disable or relabel a real organizer/staff account and preserves the
  original vulnerability.
- Do not weaken provider MFA, verified identity, CSRF, CSP, secure cookies,
  import boundaries, API scopes, audit strictness, or Redis AUTH/TLS/CA posture
  to make the local CTF path work.

## Non-Goals And Implementation Boundaries

- No range provisioning architecture, CMS/engine schema, cloud task launcher,
  range recovery, team/bracket/scoring, or submission-policy redesign.
- No change to platform OIDC/Identity Platform protocol, corporate allowlists,
  provider MFA, bootstrap elevation, or verified identity binding beyond the
  early marked-account refusal.
- No participant self-service rename (#1593), password recovery by email, MFA,
  social login, external identity binding, API-token issuance, or organizer role
  for temporary accounts.
- No durable email queue, delivery-status service, new template engine, secrets
  manager per participant, or general platform account-lifecycle framework.
- No new participant DTO/schema/repository/exception hierarchy. Django forms,
  models, CTF services/exceptions, DRF envelopes, and existing audit/email/range
  services remain the contracts.
- No preservation of magic-link compatibility. Registration views, token fields,
  token settings, JavaScript, templates, tests, and stale documentation are
  removed or rewritten together; the #1088 and #556 magic-link preflight notes
  become historical/superseded guidance.
- No Ground Control requirement or traceability work for this requirement-free
  issue.

## Whole-Repo Scope For The Follow-Up

The implementation review must account for all of these surfaces, even if some
need only regression tests or documentation updates:

- identity and auth: `management.models/services/admin`, `shared.auth`,
  `shared.api_tokens`, `config.oidc`, `config.identity_platform`,
  `config.dev_auth`, `config.views`, `_oidc_settings`, settings middleware, root
  URLs, and ASGI routing;
- CTF domain: participant/event models and migrations, participant lifecycle /
  bulk import / queries facade, authorization/audit, range task enqueue,
  scheduler event handlers, notification/template policy, forms, admin and API
  views, URL exports, context processors, and Django admin;
- presentation: dedicated login/change/reveal templates, participant admin
  templates and JavaScript, trusted email templates, platform login copy,
  navigation, and CSP/style checks;
- runtime/config: env manifest and settings tests, local `.env.example` only if
  an env binding is real, AWS/GCP runtime renderers and inventory if a tunable is
  deploy-bound, scheduler startup/heartbeat and stack-smoke coverage;
- documentation: participant and organizer guides, technical CTF/architecture
  docs, native CTF smoke test, magic-link references, and changelog security
  fragment;
- tests: CTF auth/account/lifecycle/batch/concurrency/notification/range/scheduler
  suites; shared auth/API-token/error tests; OIDC and Identity Platform identity
  invariant tests; Mission Control/SPA/DRF/WebSocket 403 sweeps; migration drift
  and PostgreSQL constraint/concurrency coverage.

## Validation Expectations

Because this work changes architecture, auth middleware, and
`shifter/shifter_platform`, the completed implementation must run the required
repository gate:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

It must also run import-linter, migration drift checks, targeted CTF/provider/
API/WebSocket tests, password/email secret-leak tests, and at least one
PostgreSQL lane for conditional uniqueness and concurrent username/capacity
creation. SQLite-only success is not evidence for those database invariants.
