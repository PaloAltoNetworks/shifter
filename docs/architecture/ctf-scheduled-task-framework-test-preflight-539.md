# CTF Scheduled Task Framework Test Preflight (#539 / CTF-1001)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: CTF-1001, "Scheduled Task Framework"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

## Scope Boundary

Issue #539 is a coverage and Ground Control traceability remediation issue. For
CTF-1001, the implementation should prove the existing CTF scheduler framework is
covered by maintained tests and a `TESTS` trace link. It should not redesign the
scheduler, add a second scheduling service, or broaden CTF-1001 into unrelated
notification, range-access, or scheduler-autostart requirements.

The CTF scheduler framework is already represented by `CTFScheduledTask`,
`ScheduledTaskType`, `ScheduledTaskStatus`, `run_ctf_scheduler`, and the event
task helpers. Test work should hold those contracts in place.

## Architecture Decisions

- Treat the existing `CTFScheduledTask` table as the durable task registry.
  `task_type`, `scheduled_for`, `status`, `error_message`, `metadata`, and the
  model transition helpers remain the framework contract.
- Keep the management command as a due-task poller. Due tasks are claimed through
  `select_for_update(skip_locked=True)`, dispatched through `TASK_HANDLERS`, and
  observed through the existing heartbeat/stale-recovery behavior.
- Cover the CTF-1001 task types named in the requirement:
  `SPIN_UP_RANGES`, `CLEANUP_RANGES`, `EVENT_START`, `EVENT_END`, and
  `SEND_REMINDER`. Existing extension types such as `RELEASE_CHALLENGE` must use
  the same registry and handler discipline, but they should not be substituted
  for the requirement's core evidence.
- Ground Control evidence must link CTF-1001 to maintained test assets with
  `TESTS`. Link tests, not implementation files, placeholders, migrated audit
  notes, or broad directories.
- Reuse the existing scheduler tests and CTF fixtures. Add narrowly scoped tests
  only where a meaningful CTF-1001 behavior is not already asserted.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Task model | `ctf.models.CTFScheduledTask` | Do not add a duplicate task table, task DTO, or queue schema. |
| Task type/status vocabulary | `ctf.enums.ScheduledTaskType`, `ScheduledTaskStatus` | Do not introduce parallel enums in tests, serializers, or fixtures. |
| Scheduler runtime | `ctf.management.commands.run_ctf_scheduler` | Preserve polling, row claiming, handler dispatch, heartbeat, stale recovery, and graceful shutdown semantics. |
| Event scheduling | `ctf.services.event._schedule_event_tasks`, `_reschedule_event_tasks`, `_cancel_event_tasks` | Verify lifecycle scheduling through these helpers rather than constructing a second orchestration path. |
| Range spin-up execution | `ctf.services.range.batch` and `ctf.services.range.tasks` | Keep long-running range work behind the existing service seam and heartbeat callback. |
| CTF service boundaries | `ctf.services.*`, `ctf.bridges` | Scheduler handlers call CTF services; they do not import CMS or Engine models directly. |
| Exceptions | `ctf.exceptions.CTFError` subclasses | Do not add scheduler-specific public exception hierarchies. |
| Error envelopes | `ctf.views._access._json_error`, `ctf.api._base`, `shared.api.errors` | HTTP/API tests should assert controlled errors, not raw scheduler exception text. |
| Logging hygiene | `shared.log_sanitize.safe_log_value`, module loggers | Keep task/event ids, counts, and statuses; do not log secrets, provider payloads, raw env, invite tokens, or email bodies. |
| Runtime health | local compose, AWS Docker deploy scripts, GCP manifests, Helm chart, stack-smoke tests | Only touch runtime manifests if command/env/probe behavior changes, and update every runtime surface together. |
| Traceability | `.ground-control.yaml`, `.gc/plan-rules.md`, Ground Control project `shifter` | Use `Brad-Edwards/shifter` and a `TESTS` link against active requirement CTF-1001. |

## Cross-Cutting Layers

- Auth surface: scheduler execution is a management-command process, while manual
  range enqueue and progress APIs stay behind session/API-token auth, CTF
  organizer role checks, CSRF-protected POSTs, and event-owner checks.
- Validation surface: task rows rely on Django model choices and
  `CTFBaseModel.save()`/`full_clean()`. Event timing and range spin-up bounds
  remain on `CTFEvent` and CTF forms, not in duplicated scheduler validators.
- Metadata shape: task metadata is a bounded JSON payload for handler parameters
  such as `hours_before`, `challenge_id`, or `source`. It must not become a
  generic command envelope, provider request body, secret carrier, or user-facing
  error store.
- Secret-handling surface: this work should add no secrets. Do not pass DB URLs,
  cloud credentials, invite tokens, API tokens, email contents, or range
  credentials through task metadata, logs, `error_message`, process argv, or test
  fixtures.
- Env-binding shape: scheduler tunables such as stale-task minutes use typed
  Django settings through `config.settings._env_int` and existing runtime env
  wiring. Do not add hard-coded environment-specific constants to scheduler code
  or tests.
- OS/runtime exposure: the runtime command remains
  `python manage.py run_ctf_scheduler`; command-line flags should stay
  non-secret bounded integers used for local polling cadence or batch size.
- Persistence: correctness is database-backed: task rows, row locks, conditional
  stale recovery, and model transition helpers. Do not replace it with in-memory
  locks, files, cache keys, or a process-local queue.
- Error-envelope surface: scheduler internals may store sanitized, truncated
  failure text in `CTFScheduledTask.error_message`; HTTP/API responses must keep
  existing controlled error envelopes and never expose stack traces or provider
  payloads.

## Extensibility Seam

The seam is the task-type registry:

- a `ScheduledTaskType` enum value;
- a `CTFScheduledTask` row with a due time, status, event, and minimal metadata;
- one handler in `TASK_HANDLERS` that delegates to the owning CTF service;
- tests that assert task creation, dispatch, status transition, failure, stale
  recovery, and handler metadata behavior.

That seam lets future CTF automation add a task type without changing the
scheduler process model, runtime deployment, or service-boundary rules.

## Gotchas And Anti-Patterns

- Do not treat a `TESTS` trace link as sufficient if the linked test only imports
  the model or checks a placeholder. It must exercise scheduler behavior that
  proves CTF-1001.
- Do not satisfy CTF-1001 with only handler unit tests; include framework behavior
  such as status transitions, due-task claiming, stale recovery, and interrupted
  work handling.
- Do not add Celery, RQ, cron-specific tables, SQS messages, background threads,
  or a second scheduler command for this requirement.
- Do not conflate task status with participant range status or event lifecycle
  status.
- Do not duplicate validation for event dates, range spin-up windows, reminder
  hours, or scenario access in scheduler tests or helper schemas.
- Do not make tests depend on real cloud providers, queue URLs, Kubernetes
  clusters, wall-clock sleeps, or live email delivery.
- Do not expose `CTFScheduledTask.error_message` directly to participants or
  organizers as an API contract.
- Do not let scheduled announcements or scheduler autostart creep into CTF-1001
  unless a separate requirement or issue explicitly changes scope.

## Non-Goals

- No implementation is performed by this preflight.
- No new scheduler infrastructure, runtime process model, task persistence model,
  exception hierarchy, public API contract, or deployment topology.
- No redesign of CTF notification content, CMS range lifecycle, Engine request
  schemas, challenge release scheduling, scoreboard behavior, or event state
  transitions.
- No Ground Control requirement creation or status transition is needed; CTF-1001
  is already active. The follow-up implementation should add a `TESTS` trace link
  to maintained test assets after coverage exists.
