# CTF Range Spinup Test Traceability Preflight (#539 / CTF-1002)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-1002` - Automated Range Spinup

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. The upcoming work should
close the CTF-1002 evidence gap with meaningful automated coverage and Ground
Control `TESTS` traceability, and should not redesign the CTF scheduler or range
provisioning stack.

## Scope Boundary

`CTF-1002` has four distinct contracts:

1. event configuration stores a bounded spin-up lead time;
2. scheduled events create one durable `SPIN_UP_RANGES` task at
   `event_start - range_spinup_minutes`;
3. the scheduler runs throttled event provisioning and continues after
   `event_start` if the event is still not fully provisioned;
4. organizers are notified when provisioning crosses event start incomplete.

The first three are already represented by `CTFEvent.range_spinup_minutes`,
`CTFEvent.get_spinup_time()`, `ctf.services.event._schedule_event_tasks`,
`run_ctf_scheduler._handle_spin_up_ranges`, and
`ctf.services.range.provision_event_ranges_throttled`. The remaining design risk
is the delay notification and traceability evidence. A `TESTS` link for this
requirement should not point only at generic scheduler startup or broad smoke
coverage.

## Architecture Decisions And Guardrails

- Reuse `CTFEvent.range_spinup_minutes` and `get_spinup_time()` as the only
  per-event spin-up schedule contract. Do not add a second event field, settings
  knob, task metadata value, or UI-only setting for the same lead time.
- Reuse `CTFScheduledTask` with `ScheduledTaskType.SPIN_UP_RANGES` as the durable
  background-work record. Do not add Celery/RQ, a cron table, a process-local
  queue, or a new scheduler task type just to detect event-start delay.
- Keep throttling in `provision_event_ranges_throttled()` and pacing in
  `compute_throttle_delay()`. The scheduler handler may pass event/task context
  and callbacks, but it must not copy the participant loop.
- Treat "delay" as distinct from "provisioning failure". Existing
  `notify_organizer_provision_failure()` covers failed participants; a
  not-yet-complete-by-start notice should use the CTF notification service and
  its own explicit notification semantics rather than reusing
  `PROVISION_FAILURE`.
- The delay notification must be idempotent through persistent state. A
  process-local flag is not sufficient because scheduler tasks can be requeued,
  retried, or claimed by another scheduler process after recovery. Use existing
  persistence surfaces such as `CTFScheduledTask.metadata` for task-scoped
  markers or `CTFNotification` for sent-notification records; do not create a
  new ledger table unless the existing rows cannot express the state safely.
- If a new notification type/template is needed, update the full notification
  contract together: `NotificationType`, `CTFNotification` choices, default
  HTML/text templates, `ctf.services.email_template.ALLOWED_PLACEHOLDERS_BY_TYPE`,
  render tests, and service tests. Do not bypass custom-template safety by
  rendering organizer-authored bodies with Django's template engine.
- Continue provisioning after event start. Event start is a notification
  threshold, not a cancellation, failure, or automatic requeue boundary.
- Ground Control `TESTS` links must point at maintained tests that assert the
  CTF-1002 behavior. Do not link this note, audit docs, fixtures, or smoke tests
  that do not exercise spin-up timing, throttling, continuation, or delay notice.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-1002 |
| --- | --- | --- |
| Spin-up schedule field | `ctf.models.CTFEvent.range_spinup_minutes`, `get_spinup_time()` | Keep model validators and `CTFBaseModel.save()` validation as the source of truth. |
| Event scheduling | `ctf.services.event._schedule_event_tasks`, `_reschedule_event_tasks` | Assert scheduled task rows through the event lifecycle path; do not duplicate scheduling math in views or fixtures. |
| Scheduled task execution | `ctf.models.CTFScheduledTask`, `ScheduledTaskType.SPIN_UP_RANGES`, `run_ctf_scheduler.py` | Reuse row claiming, heartbeat, stale recovery, interrupt/requeue, and handler dispatch. |
| Throttled provisioning | `ctf.services.range.provision_event_ranges_throttled`, `compute_throttle_delay()` | Extend via parameters/callbacks only where needed; do not copy the throttled loop. |
| Participant assignment | `ctf.services.range.provision_participant_range_with_retry` and `provision_participant_range` | Preserve participant row locking, benign already-assigned skip behavior, and retry semantics. |
| CMS boundary | `ctf.bridges.cms_create_range`, `cms_find_range_instance_id`, `cms_get_range_status` | CTF scheduler/range tests should mock at the service or bridge seam, not import CMS models directly. |
| Organizer notifications | `ctf.services.notification`, `CTFNotification`, `shared.email` | Render/send/record notices through the existing service and shared email boundary. |
| Custom email safety | `ctf.services.email_template` | Add explicit placeholders for any new notice type; keep flat scalar substitution and fail-closed validation. |
| Runtime config | `config.settings._env_int`, `CTF_SCHEDULER_STALE_TASK_MINUTES` | New runtime knobs, if unavoidable, bind through settings/env parsers with fail-loud tests. Prefer the existing event field for spin-up timing. |
| Logging hygiene | module loggers, `shared.log_sanitize.safe_log_value()` | Log event ids, task ids, counts, timings, and statuses; avoid raw provider payloads, email bodies, env dumps, and tokens. |
| Tests | `tests/ctf/test_models.py`, `tests/ctf/test_services/test_scheduler_handlers.py`, `tests/ctf/test_services/test_range.py`, `tests/ctf/test_services/test_notification.py` | Strengthen the existing focused suites instead of creating detached golden-file or smoke-only coverage. |
| Platform startup | `tests/platform/test_ctf_scheduler_startup.py`, local Compose, AWS/GCP scheduler manifests | Only touch runtime/deployment tests if command, env, or heartbeat contracts change. |

## Cross-Cutting Layers

- Auth surface: event create/update and manual organizer actions stay behind
  existing `@login_required`, `@ctf_organizer_required`, and event ownership
  checks. Scheduled spin-up runs in the trusted management command and must not
  expose a new unauthenticated HTTP or CLI control path.
- Request parsing and error envelopes: JSON APIs continue to use
  `_parse_body_object`, service validation, and `_json_error` fixed messages.
  Scheduler internals may fail task rows, but public responses must not expose
  raw exceptions, provider payloads, or task `error_message`.
- Secret-handling surface: this flow should not materialize new secrets. Do not
  place invite tokens, range credentials, cloud credentials, provider responses,
  email bodies, DB URLs, or environment dumps in task metadata, process argv,
  logs, notification bodies beyond intended organizer content, or tests.
- Config shape and validators: `range_spinup_minutes` is a Django model field
  with `MinValueValidator(0)` and `MaxValueValidator(1440)`, surfaced through
  forms and event JSON. Any new scheduler-wide threshold belongs in
  `config.settings` via the existing env parsers and must be validated in tests.
- Persistence and locking: due-task claiming remains
  `select_for_update(skip_locked=True)` on `CTFScheduledTask`. Long-running
  work must keep task `updated_at` and `/tmp/ctf-scheduler-heartbeat` fresh.
  Delay-notification idempotence must survive task requeue/recovery.
- OS/runtime exposure: the scheduler command remains
  `python manage.py run_ctf_scheduler` with its existing heartbeat file. Do not
  pass event ids, organizer emails, JSON payloads, or secrets through shell
  command lines or add host-local lock files.
- Notification safety: trusted default templates go through `shared.email`;
  organizer-authored custom templates go through `ctf.services.email_template`
  allowlists and scalar substitution. A new delay notice must not become a
  second template engine or an inline string assembled in scheduler code.
- Observability: record enough signal to debug delayed spin-up: event id, task
  id, participant totals, ready/failed/skipped/remaining counts, event start,
  and whether a delay notice was sent. Keep labels low-cardinality and sanitize
  user-controlled or external values.
- Ground Control traceability: use the repo's canonical `Brad-Edwards/shifter`
  context and add a `TESTS` link to the maintained test asset only after the
  test asserts CTF-1002 behavior. `IMPLEMENTS` links already exist for the core
  code surfaces.

## Extensibility Seam

Keep the extension point around the existing spin-up task execution:

- pacing policy: `compute_throttle_delay(spinup_window_seconds, participant_count)`;
- execution context: event id, task id, event start, and existing heartbeat /
  shutdown callbacks;
- delay-notice policy: a persistent "notice already sent" marker, remaining
  participant counts, and a notification service call;
- notification content: explicit scalar placeholders for event name, event
  start, total participants, ready count, and remaining count if a new template
  type is introduced.

That seam lets future work add a reminder cadence, capacity-aware pacing, team
allocation, or richer organizer progress without editing deployment topology,
duplicating the range loop, or creating another scheduler abstraction.

## Gotchas

- `range_spinup_minutes=0` is valid and means "start at event start". Decide
  deliberately whether this should send an immediate delay notice; do not treat
  the zero-lead-time case as an accidental infrastructure delay by default.
- A scheduler process can start late and claim `SPIN_UP_RANGES` after
  `event_start`. The delay notice should still be based on event start and
  remaining work, not on whether the handler happened to begin before the event.
- The throttling delay is clamped to `[5, 120]` seconds, so
  `range_spinup_minutes * 60` is a pacing input, not a guarantee that every
  participant finishes before event start.
- `range_instance_id is null` is not the same as "nothing is happening";
  participants can be `range_status="provisioning"` with no resolved instance
  id yet. Use the existing range-service semantics when computing remaining or
  delayed work.
- Failure notification and delay notification can both apply to the same run.
  Do not suppress failure reporting just because a delay notice was sent.
- `CTFBaseModel.save()` calls `full_clean()`. Heartbeat updates and idempotence
  markers should avoid unnecessary full-object validation churn in long loops.
- SQLite-backed tests cannot prove PostgreSQL advisory/row-lock behavior. Keep
  cross-node correctness claims tied to the established concurrency tests and
  docs, not to a single local database test.

## Anti-Patterns

- Adding a second spin-up schedule field, JSON schema, DTO, enum, or task table.
- Sending organizer email directly from `run_ctf_scheduler.py` instead of
  `ctf.services.notification`.
- Reusing `PROVISION_FAILURE` for a delay-only notice.
- Stopping, failing, or requeueing the spin-up task solely because event start
  was reached.
- Polling CMS/Engine tables from scheduler code to decide delay state when CTF
  participant state and the range service already own the workflow projection.
- Logging raw cloud/provider errors, invitation tokens, range credentials,
  organizer-authored template bodies, or full email payloads.
- Creating Ground Control `TESTS` links to docs, factories, broad platform
  startup tests, or tests that only assert the old partial implementation.

## Non-Goals

- No requirement implementation is performed by this preflight.
- No scheduler framework replacement, event state-machine redesign, range
  lifecycle rewrite, CMS/Engine contract change, or cloud provider change.
- No CTF-1006 scheduler auto-start work and no broad CTF-010 scheduled-task
  remediation beyond the CTF-1002 surfaces needed for meaningful coverage.
- No new public API surface for executing scheduled spin-up tasks.
- No Ground Control `IMPLEMENTS` trace changes are required for this preflight;
  the follow-up should reconcile only meaningful `TESTS` links for maintained
  tests.

## Validation Expectations

Architecture or `shifter/shifter_platform` changes on this path must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups that touch Python under `shifter/shifter_platform`
should also run the relevant CTF model, scheduler-handler, range-service,
notification-service, and platform scheduler-startup tests, plus ruff and
import-linter when imports change.
