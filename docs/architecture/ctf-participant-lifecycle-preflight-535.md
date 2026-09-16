# CTF Participant Lifecycle Preflight (#535 / CTF-006)

Status: pre-implementation guidance

Date: 2026-08-02

This note resolves a terminology conflict left after the isolated-account
cutover. It is a boundary record, not an implementation plan.

## Decision

Organizer add and CSV import are **seat provisioning**, not invitations that
await participant acceptance. They atomically create a fresh temporary CTF
account, link it to one event-scoped `CTFParticipant`, mark the participation
`registered`, and enqueue the existing range-provisioning workflow. An optional
delivery email carries only non-secret login information. It is not identity,
proof of receipt, or a state transition.

Consequently, the current create-then-immediately-register hop is not a
meaningful lifecycle transition. The implementation must remove that misleading
state from organizer-provisioned creation and align model/help text, endpoints,
templates, webhooks, email copy, tests, and CTF-006 wording with the
provisioned/registered vocabulary. `invited_at`, an `INVITED` status, and
`invite`/`resend invite` names must not imply an acceptance workflow when none
exists.

`registered_at` means the CTF seat and its isolated account were provisioned;
it does **not** mean the person received email, first logged in, changed the
bootstrap password, became event-active, or completed the event. Those facts
already belong respectively to notification delivery, account/password policy,
event lifecycle/access predicates, and activity/completion state. Do not add a
second timestamp or status merely to represent email delivery.

True invitation acceptance (an unlinked row followed by platform OIDC/SSO or
magic-link identity binding) is explicitly out of scope. It conflicts with the
one-fresh-temporary-account/one-seat boundary in
`ctf-isolated-participant-accounts-preflight-1206.md` and requires a separately
approved identity, token, expiry, anti-enumeration, and migration design.

## Canonical Boundaries To Reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Participant lifecycle facade | `ctf.services.participant`; `lifecycle.py`, `bulk_import.py`, `accounts.py` | Keep every organizer creation path behind one public service seam; do not put lifecycle writes in views, serializers, forms, or signals. |
| Identity and temporary-account policy | `management.services.configure_temporary_ctf_account`, `is_temporary_ctf_account`; `shared.auth.CTF_PARTICIPANT_GROUP` | Always create a fresh marked account; never look up, link, or elevate a platform user by delivery email. |
| Authentication and account confinement | `ctf.services.participant.authenticate_ctf_participant`, `config.auth.CTFParticipantBackend`, `CTFAccountBoundaryMiddleware`, `CTFAccountWebSocketBoundary` | Preserve live-account, forced-password-change, HTTP, and WebSocket gates. Status wording must not weaken any of them. |
| Access/scoring eligibility | `eligible_participant_q`, `viewing_participant_q`, `ranked_participant_q`, `assert_participant_can_compete` | Keep these predicates as the single access/ranking truth; do not scatter `registered_at` or status lists in consumers. |
| Persistence/concurrency | `CTFBaseModel.save()`/`full_clean()`, CTF participant constraints, `transaction.atomic()`, event/team `select_for_update()` | Preserve model validation, soft-delete semantics, event capacity lock, team lock, per-event delivery-email uniqueness, and one-active-participation-per-user constraint. |
| Provisioning | `ctf.services.range.request_event_provisioning()` and scheduler workflow | Enqueue on commit only; do not synchronously call CMS/engine or create a second provisioning loop. |
| Organizer boundary/API shapes | `CTF_ORGANIZER_PERMISSIONS`, `_resolve_owned_event` / `_resolve_owned_participant`, capability `"participants"`, DRF serializers, `shared.api.errors` | Retain session/API-token authentication, exact scopes, event ownership/capability checks, typed request shapes, and the shared error envelope. |
| Validation/errors/logging/audit | Django email/password validators; `CTFValidationError` family; `shared.log_sanitize.safe_log_value`; `shared.audit` | Keep validation authoritative in services/models, map controlled failures through existing envelopes, log safe identifiers only, and retain existing strict credential/audit behavior. |
| Delivery | `ctf.services.notification`, `ctf.services.email_template`, `shared.email` | Reuse queued, secret-free delivery. Call it login-information delivery, not acceptance or credential confirmation. |

## Cross-Cutting Security And Runtime Gates

- **Auth and authorization:** organizer mutations pass
  `IsAuthenticatedSessionOrApiToken`, `HasActiveCTFActor`, endpoint scopes,
  `HasCTFOrganizer`, and event-specific ownership/delegated `participants`
  capability. The service remains defensive for alternate callers. Participant
  login continues to admit only active marked temporary accounts with a live
  participation; platform/provider backends continue to reject them.
- **Request and policy shapes:** DRF serializers (and legacy form/CSV parsing
  where retained) validate transport shape. `CTFParticipant.clean()` and the
  service enforce event/team/capacity/uniqueness policy. Do not duplicate a
  lifecycle validator in each endpoint or make an email-delivery result a
  client-supplied status.
- **Secrets and OS exposure:** delivery email, username, login URL, bootstrap
  password, password hash, session, and any future token remain outside logs,
  audit payloads, webhooks, URLs, error details, task metadata, process argv,
  environment, temp files, and fixtures. Existing `sensitive_*`, encrypted
  event-password, `no-store`, and safe-log policies remain authoritative.
- **Error envelope and observability:** translate expected domain failures via
  `CTFValidationError`/`CTFStateError` and `_CtfApiError`/`shared.api.errors`;
  never serialize raw `IntegrityError`, email, cache, authentication, or model
  validation text. Reuse request-id correlation and sanitized IDs. Preserve the
  established post-commit, best-effort webhook behavior, but its event name and
  payload must say `participant_registered` only after a successful commit.
- **Repository/runtime controls:** CTF remains a domain layer using its public
  service facade and `shared` contracts under ADR-001/import-linter. No new
  configuration, OIDC exemption, authentication backend, shell command,
  background worker, API token scope, or environment secret is needed for this
  terminology/lifecycle correction.

## Extensibility Seam

The seam is the participant-account creation service, parameterized only by
existing seat inputs (event, optional delivery email, display name, and allowed
team assignment). All single, CSV, and generated-seat flows must converge
there. A future delivery channel may consume the already-provisioned
participant/account result without changing lifecycle state. A future true
acceptance flow is not a parameter on this service: it is a separate identity
product with its own durable contract.

## Gotchas And Anti-Patterns

- Do not rename an endpoint/UI label while leaving API booleans, email/template
  language, webhook event semantics, model help text, and tests claiming an
  unfulfilled invitation; that preserves the ambiguity at integration points.
- Do not retain `INVITED` as a normal row state solely for backward-compatible
  copy. Either provide one real guarded transition or remove/quarantine the
  dead state and reconcile any legacy rows deliberately. Never bulk-update
  historical rows without considering soft deletes, event state, range
  ownership, and migration safety.
- Do not use `registered_at` as delivery, login, event-active, or ranking
  evidence. Use the established predicate appropriate to compete, view, rank,
  or live-account admission.
- Do not reintroduce magic-link tokens, delivery-email identity lookup,
  platform-user linking, reversible credentials, or password email. These
  violate the isolated-account security model.
- Do not move capacity checks into serializers/forms or rely on pre-checks:
  the locked transaction and database constraints are the race-safe authority.
- Do not turn notification queue success into delivery success, and do not
  couple email failure to account provisioning unless a separate product
  decision defines compensating lifecycle semantics.

## Non-Goals

- Implementing participant changes, a new onboarding flow, self-registration,
  OIDC/SSO/magic-link binding, or a new account model.
- Changing organizer/staff roles, team/range/scoring rules, completion or
  moderation semantics, account retention, credential issuance, or API-token
  policy.
- Replacing notification infrastructure, adding another exception hierarchy,
  lifecycle schema, status machine library, audit model, or provisioning
  worker.
