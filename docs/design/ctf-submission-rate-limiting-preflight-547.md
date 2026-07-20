# CTF Submission Rate Limiting Preflight - Issue 547 / CTF-114

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/547>

## Boundary

CTF-114 is the participant/challenge submission-frequency gate. It is not the
same concept as CTF-112 attempt-count enforcement:

- submission rate limiting answers "how soon may this participant submit again
  for this challenge?";
- attempt limits answer "how many total/current-window submissions may this
  participant make for this challenge?"

The event-owned parameter is `CTFEvent.submission_cooldown_seconds`.
`0` disables the frequency gate. The scope key is the active
`(participant_id, challenge_id)` pair, using the participant's event. Do not add
an IP-wide, user-wide, team-wide, process-local, WAF, or CTFd-compatible rate
limiter for this requirement.

The current branch already contains the core incumbents (`CTFEvent` cooldown
field, `CTFRateLimitError`, `submit_flag`, and service tests). Treat the
migrated issue text and traceability as potentially stale. The implementation
work should close any remaining behavior, API, UI, or verification gaps without
creating duplicate schemas or duplicate rate-limit concepts.

## Architecture Decisions

- The authoritative gate belongs in `ctf.services.submission.submit_flag`, not
  only in views, templates, JavaScript, admin forms, middleware, or a cache. All
  flag-submission callers must get the same enforcement.
- The durable state used for the decision is `CTFSubmission` history filtered by
  participant and challenge through the default soft-delete-aware manager.
  Rejected submissions must not create a `CTFSubmission`, increment
  `attempt_number`, count against `max_attempts`, update scores, or trigger
  leaderboard recomputation.
- Concurrency correctness must stay inside the existing `transaction.atomic()`
  plus `CTFParticipant.objects.select_for_update()` submission critical section.
  A best-effort pre-check may reduce expensive flag-verifier work, but it cannot
  replace the locked check before insert.
- Flag verification may be CPU-bound or network-bound. Do not hold the
  participant row lock across external HTTP or programmable flag validation.
- `CTFRateLimitError` is the domain exception. Keep retry information in bounded
  fields such as `retry_after_seconds`, `retry_at`, and `cooldown_seconds`; do
  not add a second exception hierarchy.
- The participant-facing API should return HTTP 429 and `Retry-After` for
  cooldown rejections. If the body needs retry timing, construct an authored
  message from numeric retry details rather than returning `str(exc)`.
- The event configuration remains event-owned and model-validated. Use
  `CTFEvent.submission_cooldown_seconds`, `CTFEventForm`,
  `_EVENT_MUTABLE_FIELDS`, `_event_detail_payload`, and the admin event form
  wiring. Do not add a Django setting, environment variable, Terraform variable,
  or Kubernetes setting for per-event cooldowns.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Participant auth surface | `@login_required`, `@ctf_participant_required`, `_resolve_challenge_participant`, `_get_participant_for_challenge` | Resolve the participant scoped to the route challenge's event. Do not use unscoped participant lookup. |
| CSRF and browser POST shape | Django CSRF middleware and existing `X-CSRFToken` fetch pattern in `challenge_detail.html` | Do not add `csrf_exempt` or token-in-query shortcuts. |
| JSON parsing | `_parse_body_object` and `_get_body_str` | Keep malformed JSON and non-string flags as 400 envelopes. Do not add endpoint-local parsers. |
| Challenge availability | `assert_challenge_available_for_participant` | Keep participant eligibility, same-event, ACTIVE/window, visibility, release, and prerequisite gates before accepting a submission. |
| Event config shape | `CTFEvent.submission_cooldown_seconds`, migration `0011`, model validators, `CTFEventForm`, `ctf.services.event._EVENT_MUTABLE_FIELDS`, `ctf.views.api.events` | One canonical cooldown field. If its validation changes, update model, form, API, template, and tests together. |
| Submission persistence | `CTFSubmission` plus indexes on participant/challenge and submitted time | The submission table remains the audit and scoring ledger. No cache-only or process-local enforcement. |
| Attempt limits | `_check_attempt_limit_or_raise` and `_count_attempts_in_current_window` | Keep CTF-112 attempt-count/timeout semantics separate from CTF-114 frequency cooldowns. |
| Exceptions | `CTFRateLimitError` under `ctf.exceptions.CTFError` | Reuse existing CTF exception hierarchy and details contract. |
| Error envelopes | `_json_error`, `shared.errors.safe_user_message`, `classify_user_message` | Do not return raw exception text, submitted flags, request bodies, SQL, validator payloads, or stack traces. |
| Logging | module loggers plus `shared.log_sanitize.safe_log_value` / `safe_log_fingerprint` | Log IDs, cooldown seconds, and retry seconds only. Never log submitted flags, cookies, CSRF tokens, challenge solutions, or raw HTTP-validator config. |
| Tests | `tests/ctf/test_services/test_submission.py`, `test_api_error_paths.py`, `test_api_view_flows.py`, participant challenge view/template tests | Cover service behavior, 429/Retry-After envelope, browser display of retry timing, per-challenge scope, disabled cooldown, and no attempt-count increment on rejection. |
| Architecture gates | `.importlinter`, `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Keep CTF isolated from `engine` and `mission_control`; use shared helpers for cross-cutting behavior. |

## Security Layers

- Authn/authz: participant submits through Django session auth,
  `@login_required`, `@ctf_participant_required`, challenge-scoped participant
  resolution, and the service-level availability policy. Internal callers still
  hit the service gate.
- Request validation: `api_submit_flag` must keep the shared JSON-object parser
  and string field extraction. Empty flags stay 400 before the service call.
- Domain policy: `submit_flag` must still enforce participant eligibility,
  challenge/event match, ACTIVE event status, event time window, visibility,
  release time, prerequisites, already-solved rejection, attempt limits, and
  submission cooldown before persisting a row.
- Config validation: event cooldown values pass through the Django model field,
  `MaxValueValidator(300)`, form min/max controls, and API update allowlist. A
  future max/default change belongs in that event-config surface, not in an env
  binding.
- Secret handling: submitted flags, flag hashes, challenge solutions, session
  cookies, CSRF tokens, invite tokens, and HTTP-validator credentials are secret
  or sensitive. They must not appear in logs, test snapshots, process argv,
  shell history, screenshots, GitHub comments, or user-facing errors.
- Error envelope leakage: the user may learn the bounded retry time for their
  own submission. They must not receive raw exception strings, cross-event
  details, internal timestamps beyond the retry contract, validator errors, SQL,
  stack traces, or flag material.
- OS/runtime exposure: this feature should remain in Django/Python and the DB.
  It should not shell out, write temp files, pass flags/tokens in command-line
  arguments, or depend on process-local memory for correctness.

## Extensibility Seam

The durable seam is the event-owned cooldown policy consumed by the submission
service. If the next variation is per-challenge cooldown, team-shared cooldown,
organizer bypass, or bracket-specific policy, add a small policy resolver that
returns the effective cooldown and scope key for `submit_flag`. Do not scatter
cooldown math through views, templates, admin JavaScript, scoreboard code, or
CTF attempt-limit helpers.

The response seam is `CTFRateLimitError.details["retry_after_seconds"]` plus the
HTTP `Retry-After` header. Browser UI and API clients should derive retry
display from that bounded field, so changing from seconds-only to richer retry
metadata does not require changing the service's exception class.

## Gotchas And Anti-Patterns

- Do not conflate `submission_cooldown_seconds` with
  `attempt_limit_cooldown_seconds`; the first throttles every submission, the
  second resets a CTF-112 timeout attempt window.
- Do not implement CTF-114 with Django cache counters, LocMemCache, Redis,
  Channels, nginx/WAF rules, or IP throttles. Those are different scopes and
  weaker correctness contracts for per-participant/per-challenge submission
  history.
- Do not return the raw `CTFRateLimitError` string just to satisfy "clear
  message"; it can violate the repo's error-leakage posture. Build a fixed
  message from sanitized numeric retry data.
- Do not let the browser treat a 429 JSON response as an incorrect flag. The
  submit UI must branch on HTTP status or an explicit response field before
  rendering the result.
- Do not make rate-limited attempts visible in previous-attempt history or
  analytics. Rejections are not submissions.
- Do not use naive datetimes or client clocks. All retry math belongs on the
  server using `timezone.now()`.
- Do not make cooldown enforcement depend on challenge visibility/read UI state;
  hidden, locked, unreleased, out-of-window, or prerequisite-gated challenges
  should be rejected by availability policy before they become rate-limit cases.

## Non-Goals

- Implementing CTF-114 in this preflight note.
- Redesigning attempt limits, scoring, hints, challenge availability, flag
  verification, CTFd sync, WAF/DDOS controls, invite-token throttling, or
  scoreboard materialization.
- Adding new repositories, serializers, DTOs, exception classes, background
  jobs, env vars, Terraform variables, Kubernetes settings, or ADR exceptions.
- Backfilling historical submissions or rewriting attempt numbers.
