# CTF Challenge Release Scheduling Preflight (CTF-111)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-111` - challenge release scheduling.

This note is intentionally not an implementation plan. It records the
architecture guardrails for any follow-up work that strengthens, repairs, or
reconciles challenge release scheduling and its traceability.

## Scope Boundary

Challenge release scheduling is the transition of a challenge from
`ChallengeVisibility.HIDDEN` to `ChallengeVisibility.VISIBLE` at
`CTFChallenge.release_time`, with participant surfaces and submissions treating
unreleased content as unavailable. It is not a second event lifecycle system, a
notification scheduler, or a range-provisioning scheduler.

Keep these concepts separate:

1. Organizer configuration: challenge writes set `release_time` and
   `visibility`.
2. Participant availability: challenge lists, detail reads, hints, files, and
   flag submission enforce release and visibility through shared service policy.
3. Scheduled execution: due `CTFScheduledTask` rows are claimed and dispatched by
   `run_ctf_scheduler`.
4. Traceability: Ground Control links should point at maintained tests for this
   requirement, not at placeholders or the aggregate audit issue.

## Architecture Decisions

- Reuse `CTFChallenge.release_time`, `ChallengeVisibility`, and
  `CTFScheduledTask`. Do not add a second release table, challenge status enum,
  clock-service abstraction, scheduler queue, or visibility schema.
- Keep all challenge create/update persistence through
  `ctf.services.challenge.create_challenge()` and `update_challenge()`. HTML
  forms and JSON API views must not call `CTFChallengeForm.save()` or mutate
  `CTFChallenge` directly for organizer writes.
- Preserve `CTFChallenge.clean()` as the model invariant for release-time bounds
  relative to `CTFEvent.event_start` and `event_end`; surface validation through
  the existing form/API/service error paths rather than duplicating date rules.
- Keep release-task synchronization close to challenge service writes. A hidden
  challenge with a future `release_time` may schedule one pending
  `RELEASE_CHALLENGE` task; clearing or moving the release time must cancel the
  old pending task before creating a replacement.
- The scheduler process must keep the one-minute requirement true in deployment:
  the default `run_ctf_scheduler --poll-interval` is 30 seconds, so any future
  runtime flag, env binding, Helm value, or Docker command override must remain
  bounded to less than or equal to 60 seconds for release tasks unless the
  implementation adds an equivalent guarantee.
- Treat `LOCKED` and `HIDDEN` as different concepts. Scheduled release changes
  `HIDDEN -> VISIBLE` only; it must not unlock `LOCKED` challenges or bypass
  prerequisite gates.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Challenge persistence | `ctf.services.challenge.create_challenge`, `update_challenge`, `_CHALLENGE_MUTABLE_FIELDS` | Keep mass-assignment filtering, actor ownership, flag hashing, tag/topic handling, and release-task sync in one service contract. |
| Release invariant | `CTFChallenge.release_time`, `CTFChallenge.clean`, `CTFChallenge.is_released` | Do not duplicate release-time math in views or templates; use timezone-aware `django.utils.timezone.now()`. |
| Visibility model | `ctf.enums.ChallengeVisibility` | Preserve `hidden`, `visible`, and `locked` semantics; do not add boolean aliases such as `is_public`. |
| Participant policy | `assert_challenge_available_for_participant`, `assert_challenge_readable_for_participant`, `get_available_challenges` | All participant read/write surfaces must share the same release and visibility gates. |
| Scheduler task model | `CTFScheduledTask`, `ScheduledTaskType.RELEASE_CHALLENGE`, `ScheduledTaskStatus` | Extend existing row-claim/status behavior; no parallel task table or enum. |
| Scheduler executor | `ctf.management.commands.run_ctf_scheduler` | Preserve `select_for_update(skip_locked=True)`, heartbeat, stale recovery, signal handling, and bounded polling. |
| API parsing/error envelopes | `ctf.views._parsing`, `ctf.views._access._json_error`, `_error_tuple` | JSON write endpoints should return fixed 4xx envelopes, not raw exception text. |
| Logging hygiene | module loggers plus `shared.log_sanitize.safe_log_value` | Log task/challenge/event ids and timing, not flags, invite tokens, credentials, raw request bodies, or provider payloads. |
| Runtime/deployment | `docker-compose.yml`, AWS `user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`, GCP/Helm `ctf-scheduler` deployments | Keep scheduler command/probe parity and the `/tmp/ctf-scheduler-heartbeat` liveness contract. |
| Tests/traceability | `tests/ctf/test_challenge_release.py`, `tests/platform/test_ctf_scheduler_startup.py` | Strengthen maintained tests and Ground Control `TESTS` links; do not create trace-only placeholder tests. |

## Cross-Cutting Layers

- Auth surface: organizer configuration enters through `@login_required`,
  `@ctf_organizer_required`, event ownership checks, and the service-layer
  `actor_id` ownership assertion. Scheduled execution runs as the management
  command and must not create a public release endpoint.
- Participant access surface: participant routes use
  `@ctf_participant_required`, event-scoped participant resolution, and the
  shared challenge availability/readability policies. Release work must not
  leak hidden challenge descriptions, attachments, hints, or submission paths.
- Request shape and validation: JSON bodies go through `_parse_body_object` and
  field parsers; form input goes through `CTFChallengeForm.clean()` and
  `to_service_data()`. Model `full_clean()` remains the final invariant gate.
- Secret-handling surface: release scheduling adds no secrets. Do not store
  flags, credentials, invite tokens, environment values, or raw request payloads
  in `CTFScheduledTask.metadata`, logs, `error_message`, command argv, or env
  dumps.
- Env/config shape: no new setting is required for basic release scheduling. If
  a future poll interval or scheduler SLA knob is introduced, bind it through
  existing settings/env helpers and validate that it remains within the
  one-minute requirement.
- Persistence and concurrency: use database-backed task rows and
  `select_for_update(skip_locked=True)` for due-task claiming. Release handlers
  should be idempotent when a challenge is already visible or locked, and should
  keep task metadata to a stable `challenge_id`.
- OS/runtime exposure: the scheduler runs as `python manage.py run_ctf_scheduler`
  in Docker/Kubernetes with heartbeat probes under `/tmp`. Do not introduce host
  cron, file locks, shell-visible secrets, or a second process manager.
- Error envelopes: public API responses should retain controlled messages;
  scheduler failures may write truncated, sanitized text to
  `CTFScheduledTask.error_message`.
- Import boundaries: CTF must not import `engine` or `mission_control` directly.
  Challenge release scheduling should remain within `ctf` and shared utilities.

## Extensibility Seam

The seam is the scheduled task metadata and handler contract:

- `task_type`: `ScheduledTaskType.RELEASE_CHALLENGE`;
- `metadata.challenge_id`: stable UUID string for the target challenge;
- scheduler poll interval: bounded operational parameter that must preserve the
  one-minute release SLA;
- service hook: one helper that synchronizes pending release tasks after
  organizer-owned challenge writes.

This leaves room for future batch releases, manual organizer "release now", or
release notifications without changing participant authorization policy or
creating a new scheduler.

## Gotchas

- The aggregate audit issue and the requirement-specific tracking issue are not
  the same artifact. Keep Ground Control trace links attached to maintained
  CTF-111 tests and the requirement-specific issue where applicable.
- The audit matrix was written when CTF-111 had no explicit scheduled release
  processor. The current code has one; follow-up work should verify behavior and
  traceability before adding more runtime machinery.
- `release_time` is timezone-aware Django time. Avoid naive datetimes and string
  comparisons.
- Direct `CTFChallenge.objects.create()` in tests or scripts bypasses service
  release-task synchronization unless `_sync_release_task()` is called
  explicitly.
- `release_time <= now` should not create a future task; participant availability
  is already governed by `is_released` and visibility.
- `LOCKED` means shown but not submittable. A scheduled release should not turn a
  locked challenge into a visible/unlocked challenge.
- Changing deployment command flags can silently violate the one-minute SLA even
  when unit tests pass.

## Anti-Patterns

- Adding Celery, cron, a cache lock, an in-memory scheduler, or a new task table
  for this requirement.
- Introducing `is_visible`, `published`, or `released` booleans that compete with
  `ChallengeVisibility` and `release_time`.
- Revalidating release dates separately in every view instead of reusing the
  model/form/service validation path.
- Exposing raw `CTFError.details` or scheduler exception text to participant or
  organizer JSON responses.
- Using scheduler task metadata as a general JSON payload for challenge data.
- Creating tests only to satisfy a trace link without asserting release-time
  gating, task creation/rescheduling/cancellation, handler idempotency, and
  scheduler runtime SLA.

## Non-Goals

- No redesign of event lifecycle, reminders, scheduled announcements, range
  spin-up, scoring, prerequisites, hints, attachments, or file access.
- No new public release endpoint unless a separate requirement accepts manual
  organizer release behavior.
- No deployment topology change as part of CTF-111; preserve the existing
  scheduler process and heartbeat contracts.
- No Ground Control status transition is needed; `CTF-111` is already `ACTIVE`.
