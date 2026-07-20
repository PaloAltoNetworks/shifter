# CTF Challenge Statistics Preflight (#539 / CTF-407)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-407` - Challenge Statistics

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. Issue #539 is a coverage
and Ground Control `TESTS` traceability remediation issue, but CTF-407 also has
two correctness risks called out by the audit: solve-rate denominator drift and
unclear participant visibility.

## Scope Boundary

CTF-407 is the event-scoped per-challenge statistics contract:

- total correct solves;
- solve percentage;
- total submission attempts;
- first blood holder;
- organizer visibility at all times;
- optional participant visibility configured per event;
- updates visible within 30 seconds.

It is not a new leaderboard, scoring mode, CTFd sync layer, analytics warehouse,
background aggregate table, websocket feed, or Mission Control reporting area.

## Architecture Decisions And Guardrails

- Keep `ctf.services.scoring.get_challenge_statistics()` as the canonical
  service contract. Fix or extend this service, then render from it; do not
  duplicate statistics calculations in views, templates, admin classes, or test
  helpers.
- Compute the CTF-407 solve percentage against the event participant
  denominator, not distinct submitters. The current implementation's
  submitter-denominator behavior is a known requirement mismatch.
- Make the participant denominator explicit in the service contract or in one
  small helper. For CTF-407 evidence, use the event roster denominator that
  backs `event_stats.participant_count`; future variations such as eligible-only,
  registered-only, team, or bracket denominators should be explicit parameters
  rather than silent reinterpretations of `solve_rate`.
- Treat participant visibility as a separate event policy from
  `scoreboard_visible`, `scoreboard_freeze_at`, and `rating_visibility`.
  Challenge difficulty statistics and ranking visibility are related UI
  concepts, but not the same contract.
- Organizer surfaces must ignore the participant visibility toggle. Organizers
  keep real-time analytics and challenge-detail statistics even when
  participants cannot see challenge stats.
- The 30-second update requirement can be met by authoritative ORM reads from
  committed `CTFSubmission` and `CTFParticipant` rows on page/API load. Do not
  add a cache or background materialization unless a later performance problem
  proves it is needed. If a participant-side live refresh is added, keep its
  interval configurable at the view/template seam and no greater than 30 seconds.
- Keep first blood as a derived read from earliest correct submission. Expose
  only participant display name and timestamp where needed; never expose email,
  IP address, submitted flag, flag hash, or internal user identifiers.
- Ground Control `TESTS` links must point to maintained tests that assert the
  CTF-407 behavior. Do not link placeholder tests, factories, audit docs, or
  broad modules where challenge statistics are incidental.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Statistics service | `ctf.services.scoring._stats.get_challenge_statistics`, re-exported via `ctf.services` | One source for solve count, attempt count, first blood, and solve percentage. |
| Source rows | `CTFChallenge`, `CTFParticipant`, `CTFSubmission` | Statistics stay authoritative and event-scoped; do not use process-local counters or files. |
| Organizer analytics | `ctf.views.admin_analytics`, `templates/ctf/admin/analytics.html` | Render service results through the existing organizer page and ownership checks. |
| Organizer challenge detail | `ctf.views.admin_challenge_detail`, `templates/ctf/admin/challenge_detail.html` | Organizer-visible first blood and counts remain available regardless of participant policy. |
| Participant challenge surfaces | `ctf.views.participant_challenges`, `challenge_detail`, participant templates | Hide or show stats through an event policy gate, not template-only assumptions. |
| Event config | `CTFEvent`, `_EVENT_MUTABLE_FIELDS`, `CTFEventForm`, `api_event_detail`, `templates/ctf/admin/event_form.html` | Any new visibility flag must pass through model, migration, service allowlist, form/API payload, and edit/create UI together. |
| Participant eligibility vocabulary | `ctf.services.participant.eligible_participant_q` | Use it only when the explicitly named denominator is eligible participants; do not smuggle it into `total participants`. |
| Auth and ownership | `@login_required`, `ctf_organizer_required`, `ctf_participant_required`, `_get_active_participant`, `_resolve_owned_event_json` | Group role is not enough; event ownership and event-scoped participant membership still apply. |
| API boundary | legacy CTF JSON views, `ctf.api._base.CTFLegacyAPIView`, `shared.api.errors.api_error_response` | If a stats API is added, delegate to the same service and preserve existing error envelopes and API-token scopes. |
| Logging hygiene | module loggers plus `shared.log_sanitize.safe_log_value` | Log bounded IDs/counts/status only. Do not log flags, invite tokens, cookies, CSRF tokens, API tokens, or raw request bodies. |
| Import boundaries | `.importlinter`, `scripts/adr_guard/adr_guard.py` | CTF must not import `engine` or `mission_control` directly; cross-domain behavior goes through `ctf.bridges` and `shared`. |

## Cross-Cutting Layers

- Auth surface: organizer HTML views pass Django session auth,
  `ctf_organizer_required`, and event-owner checks; participant HTML views pass
  session auth, `ctf_participant_required`, and active-event/event-scoped
  participant resolution. A new API surface must also pass the CTF DRF wrapper
  permissions and declared read scopes.
- Validation surface: route UUIDs stay in Django URL converters; JSON bodies use
  `_parse_body_object`, `_parse_body_uuid`, `_get_body_str`, and DRF
  `JSONBodySerializer` where applicable. A new event visibility flag must be a
  typed Django model field with migration, model/form/API validation, and
  service allowlist coverage.
- Domain policy surface: statistics must remain scoped to the challenge's event,
  count all non-deleted submission attempts for that challenge, count correct
  solves once per participant through the existing correct-submission invariant,
  and use the named event participant denominator.
- Secret-handling surface: submitted flags, flag hashes, challenge solutions,
  invite tokens, emails, IP addresses, cookies, CSRF tokens, API tokens, and
  validator payloads must not appear in stats payloads, templates, logs, test
  snapshots, GitHub comments, Ground Control reports, process argv, or temp
  files.
- Config/env surface: CTF-407 should not add process-global settings,
  Terraform, Kubernetes, Helm, or Docker env for visibility. Visibility is
  event-owned data; a future refresh interval, if introduced, belongs as a
  bounded template/API parameter rather than a secret-bearing env var.
- Error-envelope surface: HTML keeps controlled `Http404` or authored 403
  responses. JSON keeps `{"error": ...}` for legacy CTF endpoints or the shared
  DRF envelope under `/api/v1/ctf/`; never return raw `CTFError.details`, SQL,
  stack traces, or ownership internals.
- Persistence and freshness surface: authoritative ORM reads from committed
  rows are the source of truth. The existing materialized leaderboard is for
  scoreboard hot paths, not challenge statistics. Do not add cache-only stats or
  a second rebuild command for this requirement.
- OS/runtime surface: this work should stay inside Django, pytest, Ground
  Control, and GitHub traceability operations. Do not pass credentials or
  tokens in shell argv, write exported statistics to `/tmp`, or depend on
  process-local memory for correctness.

## Extensibility Seam

The seam is an event-scoped challenge-statistics read model with explicit
parameters:

- `challenge_id`;
- viewer class: organizer or participant;
- participant visibility policy from the event;
- participant denominator policy, defaulting to the event roster for CTF-407;
- optional future bracket/team/category filters;
- optional refresh interval bounded to 30 seconds for participant live refresh.

This leaves room for per-bracket solve rates, team-mode statistics, category
difficulty summaries, or polling without editing templates to recalculate
domain data or creating a second statistics schema.

## Gotchas And Anti-Patterns

- Do not keep using distinct submitters as the solve-rate denominator while
  labeling the result `solve_rate` or `solve_percentage` for CTF-407.
- Do not gate challenge stats with `scoreboard_visible` or
  `scoreboard_freeze_at`. A hidden scoreboard does not automatically mean hidden
  difficulty stats, and a frozen scoreboard does not freeze organizer analytics.
- Do not leave `challenge.solve_count` unconditional in participant templates if
  participants can be configured not to see challenge stats.
- Do not add a new `ChallengeStats` model, cache table, queue worker, websocket,
  API-token scope family, exception hierarchy, DTO/schema package, or
  repository layer for this requirement.
- Do not expose first blood as email, user id, participant id, IP address, or
  full submission record to participants.
- Do not satisfy traceability with a test that only imports the service or
  asserts a mocked dict. Tests should use persisted CTF rows for denominator,
  attempts, first blood, organizer visibility, and participant visibility.
- Do not weaken `.importlinter`, ADR guard, CSRF/session auth, API-token scope
  checks, or Ground Control traceability rules to make coverage easier.

## Non-Goals

- No implementation is performed by this preflight.
- No new Ground Control requirement or status transition; `CTF-407` is already
  active and issue #539 is the traceability-remediation driver.
- No redesign of scoring, scoreboard ranking, team scoring, challenge release,
  hint penalties, range provisioning, notification scheduling, CTFd sync, or
  platform infrastructure.
- No ADR registry update is needed unless future implementation changes an
  enforceable architecture rule or guardrail file.
