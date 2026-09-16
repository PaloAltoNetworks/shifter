# Participant Password One-Time Reset Preflight (#1924)

Status: pre-implementation guidance

Date: 2026-07-31

Issue: GitHub #1924, "Replace participant password reveal with a one-time
reset flow"

This issue is requirement-free. Its title, body, and acceptance criteria are
the shipping contract. This note fixes the repository-wide credential boundary
before implementation; it is not an implementation plan.

This note supersedes the password-source, reveal, resend, and delivery
decisions in the #1206 and #1665 preflights. Their temporary-account origin,
participant isolation, forced-change, provider segregation, and cleanup
boundaries remain authoritative.

## Decision Boundary

Participant password administration is an issuance operation, never a read
operation.

- A participant account stores only Django's password hash. No UI, API,
  serializer, template, form initial value, service, audit row, notification,
  or compatibility endpoint may reconstruct or return the current password.
- New accounts use a CSPRNG-generated password by default. An event may instead
  use its encrypted shared participant password only after its owner explicitly
  enables that event policy. The deployment-wide
  `CTF_DEFAULT_PARTICIPANT_PASSWORD` fallback is not an explicit event policy
  and must no longer select account-creation behavior.
- An authorized event actor may reset one participant to a new generated
  password or set one supplied compliant password. Both are administrator-known
  credentials, so both set the existing `must_change_password` quarantine.
- Plaintext exists only in the synchronous create/hash or reset/hash/response
  call chain. For reset/set it is returned in the successful POST response and
  displayed in volatile UI state once. It is not persisted for replay. Losing
  the response requires another reset, which creates a different credential.
- Event shared-password policy and a participant reset are separate
  operations. Changing the event policy does not rotate existing accounts;
  resetting one participant does not change event policy.
- Existing password hashes remain valid until an explicit reset or the
  existing participant lifecycle disables them. There is no bulk silent
  rotation or attempt to migrate hashes back to plaintext.

No new credential repository, encryption primitive, password policy,
authentication backend, exception hierarchy, audit store, or workflow engine
is justified. The required seam is a narrow evolution of the existing
participant-account service.

## Canonical Domain Shape

The current `effective_bootstrap_password()` function conflates creation
policy, reset, reveal, email delivery, and bootstrap-reuse checks. That
conflation must end:

- **Creation policy** selects `generated` unless the event has an explicitly
  enabled shared-password policy. The existing encrypted
  `CTFEvent.participant_password_override` may remain the stored shared value;
  its presence can represent the initial two-state policy, so a new provider
  framework or second secret table is unnecessary.
- **Participant issuance** accepts one closed intent: generate a new value or
  validate an organizer-supplied value. It hashes the value, restores the
  force-change flag, revokes defensive participant API tokens, writes strict
  audit, and returns a short-lived issuance result to the immediate caller.
- **Participant password change** continues through Django
  `PasswordChangeForm`. Reuse prevention checks the current password hash and,
  when enabled, the current event shared value inside the service; it does not
  expose a general-purpose shared-password getter to presentation code.
- **Event policy mutation** is owner-only configuration. Its read projection is
  a non-secret state such as `generated` or `shared`; the shared value is
  write-only and replace-only. A blank edit must not accidentally echo,
  preserve by round-trip, or clear an existing value without an explicit
  disable action.

A small immutable issuance result is warranted because the plaintext and its
non-secret identifiers must travel together without returning a model or a
generic dictionary. It contains only the participant id, event id, username,
issued password, and low-cardinality issuance kind. It must not be persisted,
serialized into tasks, placed in a Django message, or reused as an event-policy
DTO.

The extensibility seam is the issuance intent, not a credential-provider
abstraction: a future compliant generation profile can be selected inside the
generator without changing controllers, audit, or one-time delivery. Event
creation policy remains separately parameterized (`generated` versus
`event_shared`) so a future event policy does not become a per-participant reset
mode by accident.

## Existing Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1924 |
| --- | --- | --- |
| Account lifecycle | `ctf.services.participant.accounts`, its public `ctf.services.participant` facade, event row locks, and Django transactions | Keep create, attach, reset, profile marking, token revocation, and provisioning enqueue behind this service. Do not put password mutation in a view, serializer, React hook, notification service, or repository wrapper. |
| Account persistence | Django `User.objects.create_user`, `User.set_password`, configured password hashers, and `management.services.set_ctf_password_change_required` | Store only the hash and existing force-change state. Do not add a participant password column or reversible per-account field. |
| Password validation | `django.contrib.auth.password_validation.validate_password`, `AUTH_PASSWORD_VALIDATORS`, and `PasswordChangeForm` | Generated, event-shared, and organizer-supplied values all pass the same validators with the target user context where available. Client checks are ergonomic only. |
| Secret generation | Python `secrets`, already used by participant usernames, team codes, and API tokens | Use a CSPRNG with sufficient entropy and a bounded validate/regenerate loop. Do not use `random`, timestamps, UUID display strings, settings-import generation, or a repository literal. |
| Event shared-secret storage | `CTFEvent.participant_password_override`, `shared.field_encryption.EncryptedStringField`, and `FIELD_ENCRYPTION_KEY` | Keep the event value encrypted at rest because future account creation must use it. Never project its decrypted value or bind it as an edit-form initial value. |
| Authorization | `CTF_ORGANIZER_PERMISSIONS`, `HasCTFEndpointScope`, `_resolve_owned_participant`, `_resolve_owned_event`, and `ctf.services.event.actor_has_event_capability` | Global organizer status is not event authority. Participant reset may reuse the existing `participants` capability; shared-policy mutation stays event-owner-only like other event configuration. Recheck capability in the service as defense in depth. |
| API shape | DRF serializers/views under `ctf.api`, `ctf.api.organizer._base`, `shared.api.errors`, and generated OpenAPI/types | Add one POST-only reset/set operation with a write-only request password and a one-time response field. There is no GET/retrieve operation and no hand-written frontend DTO. |
| Browser transport | `frontend/src/api/client.ts`, `ctfAdmin.ts`, TanStack Query's no-mutation-retry default, and shadcn dialog/alert primitives | Preserve same-origin cookies, CSRF, request ids, and shared errors. Keep the result out of query data/global stores and clear mutation/component state on dismiss and unmount. |
| Cache posture | `never_cache` and the `private, no-store` credential-response precedent in CTF/Mission Control VPN delivery | Reset/set responses and any server-rendered one-time result are non-cacheable and vary on cookie/authorization where applicable. The value never enters redirects, URLs, history state, or service-worker caches. |
| Rate limiting | `shared.credential_delivery.credential_delivery_allowed`, `shared.rate_limit.consume_fixed_window`, and the Redis-backed `launch_rate_limit` cache | Consume the existing cross-worker actor budget after authorization. Cache failure fails closed through a controlled 503; exhaustion returns the shared 429 envelope and `Retry-After`. Do not add process-local counters. |
| Sessions and credentials | Django session auth hashes, `must_change_password`, `CTFAccountBoundaryMiddleware`, `CTFAccountWebSocketBoundary`, and `shared.api_tokens` | Saving a new password invalidates existing Django sessions on their next authentication check; do not call `update_session_auth_hash` for an organizer reset. Restore quarantine and revoke defensive participant tokens in the same transaction. Existing all-socket denial remains. |
| Audit | `shared.audit.AuditEvent`, `AuditAction`, `AuditEntityType`, `RequestAudit`, request attribution helpers, and strict audit behavior | Use `AuditEntityType.USER` with the participant user's integer id and the existing update action; record participant id, event id, issuance kind, actor, request attribution, and a stable reset/set context only. Timestamp comes from the audit store. Event-policy mutation is a separate strict, secret-free configuration audit. No password, hash, email body, delivery address, or session key enters state/context. |
| Logging/errors | `RequestIDMiddleware`, `shared.log_sanitize`, `CTFValidationError`, `_CtfApiError`, and `shared.api.errors` | Log stable ids, result category, and request id only. Map policy/validation/auth/rate failures to controlled envelopes; never serialize raw Django validation, database, encryption, email, or cache exceptions with secret-bearing input. |
| Client accessibility | Existing dialog, form, alert, focus, and live-region patterns in `frontend/src/components/ui` and CTF admin pages | Confirmation identifies the participant and effect; generated versus supplied choice is explicit; result dialog traps focus, announces success without announcing the password, and clears/focus-restores on dismissal. |

## Cross-Cutting Layers The Design Must Pass

### Authentication, authorization, and request admission

- `ApiTokenAuthentication` / `SessionAuthentication`,
  `IsAuthenticatedSessionOrApiToken`, `HasActiveCTFActor`,
  `HasCTFEndpointScope`, and `HasCTFOrganizer` remain the outer gates.
- Session requests remain CSRF-protected by DRF `SessionAuthentication` and
  `CsrfViewMiddleware`; the SPA continues to send `X-CSRFToken`. API-token
  callers remain limited to the existing exact CTF event-write scope rather
  than receiving a new wildcard or bypass.
- `_resolve_owned_participant(..., capability="participants")` prevents
  cross-event targeting. The service repeats the same event capability check
  under the participant lock so alternate callers cannot bypass it.
- Event shared-policy changes use owner-only event configuration authorization,
  not the delegated participant-management capability. A reset dialog must not
  edit event policy as a side effect.
- The rate limiter runs only after the target is authorized, uses the shared
  cross-worker cache, and fails closed when that dependency is unavailable.

### Shape and policy validation

- A typed DRF request serializer accepts a closed issuance choice. The supplied
  password is optional only for generated mode and required only for explicit
  set mode; unknown keys/modes do not become service kwargs.
- The service is the authoritative password-policy gate and invokes Django
  validation for every source. Serializer and React length hints must not copy
  the validator suite.
- Event policy input is write-only. Reads expose only safe state such as
  `shared_password_enabled`/policy mode; they never return placeholders whose
  value could be mistaken for the secret.
- Existing CTF domain errors remain the only domain hierarchy. HTTP adapters
  map stable domain codes to the shared error envelope with request id.

### Persistence, transaction, and session invalidation

- Lock the live participant and select its event/user/profile before
  authorization and mutation. Reject missing, deleted, unmarked, inactive, or
  non-isolated accounts through existing CTF errors.
- Password hash update, force-change restoration, defensive API-token
  revocation, and strict audit are one transaction. An audit failure rolls the
  credential mutation back.
- Do not persist issuance/replay state. A repeated POST is a new reset with a
  new password, not retrieval or idempotent replay. The frontend must never
  auto-retry the mutation.
- Django's session-auth-hash mismatch is the canonical browser-session
  invalidation policy. Existing participant WebSocket denial and account
  middleware stay authoritative; range guest credentials and established
  provider sessions are different concepts and are not rotated by this action.

### Secret-handling and runtime exposure

- The reset/set value is present only in the HTTPS JSON request when supplied,
  service locals, the password hasher, the immediate HTTPS response, and
  volatile DOM/React state until dismissal. Decorate HTML POSTs with
  `sensitive_post_parameters` and service locals with `sensitive_variables`;
  ensure JSON-body/APM logging remains disabled.
- The response carries `Cache-Control: private, no-store` and appropriate
  `Vary` headers. It is never a redirect target, query parameter, fragment,
  route state, Django message, cookie, notification, email body, analytics
  event, clipboard automation, download, screenshot fixture, or test snapshot.
- TanStack mutation data is a cache surface. Use a reset-specific hook with no
  automatic retry, zero retention after it becomes inactive, and explicit
  `reset()`/local-state clearing on dialog dismissal and component unmount.
  Never invalidate or seed a participant query with the issuance response.
- No password or hash enters a Celery/scheduler/thread job payload,
  `CTFNotification`, webhook, audit JSON, log line, metric label, OpenAPI
  example, process environment, `argv`, shell string, temp file, Terraform
  value/output, Kubernetes object, CI annotation, or provider secret API.
- The event shared password is the sole reversible credential in this feature.
  It stays in the existing encrypted field and `FIELD_ENCRYPTION_KEY` posture;
  it does not move to `CTF_DEFAULT_PARTICIPANT_PASSWORD`, a ConfigMap, or a
  second encryption wrapper.

### Errors and observability

- Validation, permission, not-found, throttling, cache-unavailable, and audit
  failure responses use `shared.api.errors` with bounded messages and request
  ids. The issued/supplied password and raw exception text never appear in
  `message` or `details`.
- Audit identifies actor, participant, event, time, and whether the operation
  was generated reset or organizer-supplied set. Use
  `AuditEntityType.USER`/`AuditAction.UPDATE` with a stable low-cardinality
  context; do not add a duplicate password-reset action enum or record policy
  values or validator input.
- Operational logging records action/outcome plus safe internal ids/request id.
  Secret-redaction tests must inspect logs, audit rows, notifications, webhook
  payloads, response errors, and frontend diagnostics—not only the database.

### Configuration and OS/runtime shape

- The default-generated path needs no environment setting. Retire
  `CTF_DEFAULT_PARTICIPANT_PASSWORD` from `_oidc_settings` and the generated env
  manifest instead of retaining a silent deployment-wide policy.
- `FIELD_ENCRYPTION_KEY` remains required through the existing runtime secret
  hydration and config validation because event shared policy still needs it.
  No new secret binding, env parser, Terraform variable, or Helm/Kubernetes
  value is introduced.
- Password material is HTTP-body data only. It never crosses process argv,
  worker metadata, environment dumps, access logs, or OS temporary storage.

## Organizer Surfaces And Compatibility

All surfaces must converge on the same service and one-time contract:

- The legacy participant detail page must stop calling
  `effective_bootstrap_password` and remove the `<details>` reveal block.
- `CTFEventForm` currently uses `PasswordInput(render_value=True)` for the
  decrypted event value. That is a second persistent reveal and must be
  replaced by explicit set/replace/disable policy controls that never bind the
  stored secret as initial HTML.
- The SPA participant detail and list currently expose "Resend invitation"
  actions backed by `/resend-invite/`. Replace credential-reset meanings with
  the explicit generated/set dialog. Invitation-only messaging, if retained,
  must not mutate or carry a password.
- `send_invitations()` and `reset_participant_credentials()` currently couple
  password reset to two plaintext emails. They must not remain an alternate
  credential-administration path. Notification records, scheduled sends, and
  email threads/jobs never receive password material.
- Django admin does not currently expose the event password field in its
  explicit fieldsets; keep it that way. Do not add a generic admin reveal.

The published v1 `POST /api/v1/ctf/participants/{id}/resend-invite/` operation
is an architecture trap: silently deleting it, changing its default semantics,
or changing its status contract conflicts with ADR-040. Leaving it as a
password-reset/email path conflicts with #1924. The implementation must make
that conflict explicit through the repository's documented compatibility
process: add the independent reset/set operation additively, deprecate the old
operation, and obtain a narrowly scoped ADR-040 exception (owner, expiry,
affected operation, and migration evidence) for disabling the old
credential-mutating behavior. Do not repurpose it under the same operation id
and call the change backward-compatible.

## Creation Semantics

Every creation/attachment path (`create_participant_accounts`,
`attach_isolated_account`, single invite, CSV import, and generated batch) uses
the same creation-policy selector:

- no event shared policy: generate and validate a fresh password per account,
  hash it, and discard the plaintext;
- event shared policy enabled: validate the encrypted event value through the
  same Django policy before hashing it for the new account.

Creation does not make a generated password retrievable. Manual delivery is the
explicit per-participant reset/set operation. A future creation-time one-time
handoff may reuse the issuance-result/delivery rules, but a batch plaintext
export, stored creation receipt, notification payload, or later credential GET
is not part of #1924.

Existing non-blank event overrides map to enabled shared policy for compatibility.
Blank events become generated-by-default. The deployment-wide default is not
copied into events automatically because that would opt events into shared
credentials without an event-owner decision. Existing account hashes are not
changed by this policy interpretation.

## Whole-Repo Scope

The implementation must evaluate these surfaces together:

- architecture: ADR-009, ADR-029, ADR-036, ADR-040; the #1206, #1372, and #1665
  preflights; and the API versioning policy;
- participant domain: `ctf/services/participant/accounts.py`, `lifecycle.py`,
  `bulk_import.py`, `auth.py`, the public service facades, CTF exceptions,
  event/participant models, and migrations;
- HTTP/contracts: `ctf/api/organizer/participants.py`, serializers, URL exports,
  ownership helpers, legacy JSON adapters, HTML views/forms/templates, OpenAPI
  generation, committed `openapi/v1.json`, and generated `schema.d.ts`;
- frontend: `frontend/src/api/client.ts`, `queryClient.ts`, `ctfAdmin.ts`,
  participant list/detail pages and tests, shared dialog/form primitives, route
  unmount behavior, and any analytics/error reporting hooks;
- authentication/session: Django password validators/hashers/sessions,
  `management.services`, `CTFAccountBoundaryMiddleware`,
  `CTFAccountWebSocketBoundary`, provider backends, and shared API-token
  authentication/revocation;
- cross-cutting security: `shared.field_encryption`, `shared.credential_delivery`,
  shared rate limiting/Redis config, `shared.audit`, request attribution,
  `shared.api.errors`, `shared.log_sanitize`, browser policy, CSRF, secure
  cookies, and response cache headers;
- notification/workflow: CTF invitations, notification records/templates,
  scheduled sends, email helpers, webhooks, provisioning callbacks, and every
  payload/logging test that could capture account material;
- config/runtime: `_oidc_settings.py`, `_env_manifest.py`, generated
  `env-manifest.json`, `FIELD_ENCRYPTION_KEY` hydration, deployment inventories,
  and secret scans if the retired platform default is wired anywhere; and
- enforcement: `.importlinter`, ADR guard, API drift/breaking-change gates,
  Django tests, frontend lint/typecheck/Vitest/axe/Playwright, and secret
  scanning. Changes touching architecture or `shifter_platform` still require
  the repository's full ADR CI guard.

## Gotchas And Anti-Patterns

- Do not rename "reveal" to "reset" while still resolving and displaying the
  event shared password.
- Do not treat event shared policy as the reset default. Reset intent is
  generated or organizer-supplied; event policy controls creation only.
- Do not conflate a global organizer, event owner, delegated participant
  manager, participant user, delivery email, or event policy.
- Do not place password validation only in a serializer/form, copy Django's
  validators into React, or return the submitted password in validation
  details.
- Do not put plaintext in model fields, audit state, notifications, email,
  webhooks, tasks, messages, query caches, browser storage, URLs, downloads,
  logs, metrics, exception traces, or compatibility responses.
- Do not use a GET, replay token, reset-result id, server cache, session key, or
  signed URL to retrieve the result later. A new POST means a new password.
- Do not auto-retry after a timeout. The server may have committed; the operator
  must explicitly reset again and receive the newly issued value.
- Do not call `update_session_auth_hash` for the target participant or invent a
  session table scanner. Django's existing auth-hash invalidation is the policy.
- Do not clear/replace an event shared secret through an ordinary event edit
  whose password field was left blank. Require explicit policy intent.
- Do not preserve reset-by-email or batch-send as a hidden alternate path.
- Do not hand-maintain frontend credential DTOs or weaken ADR-040/API-contract
  checks to make the endpoint change pass.
- Do not add a password strategy registry, credential repository, encryption
  service, session revocation subsystem, audit action hierarchy, background
  delivery job, or new rate-limit cache.

## Non-Goals And Boundaries

- No implementation code, endpoint, serializer, migration, form, component,
  test, generated artifact, or runtime configuration change is made by this
  preflight.
- No recovery of existing participant passwords and no bulk export or
  migration of plaintext credentials.
- No change to provider authentication, organizer identity, participant account
  origin, role/group vocabulary, public registration, MFA, participant
  password-change UX, or Django password hashers.
- No automatic rotation when event shared policy changes and no bulk
  participant reset.
- No redesign of invitation durability, email infrastructure, event/range
  provisioning, scoring, team/bracket behavior, account retention, or range
  guest credentials.
- No new infrastructure secret, environment-driven password default,
  background credential delivery, passwordless login, recovery code, or
  participant MFA flow.
