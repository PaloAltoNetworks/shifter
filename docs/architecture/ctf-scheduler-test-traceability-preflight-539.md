# CTF Scheduler Test Traceability Preflight (#539 / CTF-010)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-010` - Scheduled Tasks & Automation

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. The issue is about
meaningful automated coverage and Ground Control `TESTS` traceability for the
existing CTF scheduler requirement. It is not a mandate to redesign scheduler
execution or add another automation framework.

## Scope Boundary

`CTF-010` is satisfied through the existing durable scheduler path:

1. event lifecycle services create and cancel `CTFScheduledTask` rows;
2. `run_ctf_scheduler` claims due rows and dispatches by `ScheduledTaskType`;
3. CTF services perform event transitions, range provisioning/cleanup, reminder
   delivery, and challenge release;
4. platform manifests and scripts start the scheduler process and expose its
   heartbeat.

The test/traceability work should prove these contracts where they already live.
Do not move scheduler policy into views, tests, deployment files, or Ground
Control metadata.

## Architecture Decisions And Guardrails

- Reuse `ctf.models.CTFScheduledTask`, `ctf.enums.ScheduledTaskType`, and
  `ctf.enums.ScheduledTaskStatus` as the only scheduler task contract. Do not
  introduce alternate DTOs, status enums, JSON schemas, or task registries.
- Treat `ctf.services.event._schedule_event_tasks`,
  `_reschedule_event_tasks`, `_reschedule_live_event_schedule`, and
  `_cancel_event_tasks` as the scheduling contract for event lifecycle changes.
  Tests may call public lifecycle services first and assert the durable task rows
  they create, but should not duplicate the scheduling algorithm in fixtures.
- Treat `ctf.management.commands.run_ctf_scheduler.Command` and
  `TASK_HANDLERS` as the execution contract. Coverage should exercise claiming,
  stale recovery, interrupt/requeue, status transitions, and handler dispatch
  through the incumbent command/handler surface.
- Range automation must continue through `ctf.services.range` and `ctf.bridges`.
  Scheduler tests should mock at the service or bridge seam, never import CMS
  models or recreate range provisioning loops in the scheduler command.
- Reminder automation must continue through `ctf.services.notification`.
  Scheduled reminder tests should verify metadata interpretation and delivery
  handoff without bypassing the existing template/recipient validation.
- Deployment coverage belongs in the platform tests that already inspect local
  Compose, AWS deploy scripts, GCP manifests, and Helm rendering. Do not rely on
  a single replica or a process manager change as proof that scheduler semantics
  are correct.
- Ground Control `TESTS` links must point at maintained test assets that assert
  behavior, not at this preflight note, generic audit documents, or placeholder
  smoke checks.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-010 coverage |
| --- | --- | --- |
| Scheduled task persistence | `ctf.models.CTFScheduledTask` | Assert durable rows, status transitions, metadata, `scheduled_for`, `executed_at`, and `error_message` behavior on this model. |
| Task type/status contract | `ctf.enums.ScheduledTaskType`, `ScheduledTaskStatus` | Use enum values; do not hard-code parallel string sets in tests or helpers. |
| Event scheduling | `ctf.services.event` lifecycle helpers | Cover create/reschedule/cancel behavior through event lifecycle flows or the internal helper when no public service exists. |
| Scheduler execution | `ctf/management/commands/run_ctf_scheduler.py` | Build on `_fetch_due_tasks`, `_recover_stale_tasks`, `_execute_task`, and `TASK_HANDLERS`; do not add a second runner. |
| Range work | `ctf.services.range.provision_event_ranges_throttled`, `cleanup_event_ranges` | Mock the service boundary for scheduler tests; keep provider/CMS behavior in range-service tests. |
| Reminder work | `ctf.services.notification.send_reminder` | Verify scheduler handoff and metadata; keep email template and recipient validation in notification tests. |
| Concurrency and liveness | `docs/architecture/ctf-scheduler-concurrency-preflight-942.md` | Reuse the row-lock, heartbeat, stale-task, and shutdown/requeue assumptions already documented there. |
| Runtime config | `config.settings._env_int`, `CTF_SCHEDULER_STALE_TASK_MINUTES` | New scheduler knobs, if any are unavoidable, must bind through settings and be fail-loud on invalid env values. |
| Logging hygiene | module loggers, `shared.log_sanitize.safe_log_value()` | Logs may include task ids, event ids, counts, and task types; avoid raw secret/env/provider payloads. |
| Error envelopes | `ctf.views._access`, `ctf.views.api._common`, `shared.api.errors` | Public API behavior should keep existing envelopes; scheduler failures remain internal task state/logs. |
| Deployment startup | `tests/platform/test_ctf_scheduler_startup.py` | Reuse manifest/script invariants instead of inventing a new deployment assertion style. |

## Cross-Cutting Layers

- Auth surface: organizer-triggered scheduling and manual provisioning stay behind
  the existing CTF view/API permission checks. The scheduler command is a trusted
  runtime process and must not expose a new unauthenticated HTTP or CLI control
  path.
- Secret-handling surface: CTF scheduler tests should not place cloud
  credentials, invite tokens, email bodies, database URLs, or service tokens in
  task metadata, argv, logs, or assertions. Task ids, event ids, task types,
  counts, and reminder hour integers are non-secret.
- Env-binding shape: scheduler runtime configuration belongs in
  `config.settings` using existing parsers such as `_env_int`. Tests that touch
  env parsing must isolate environment mutation and assert fail-loud behavior
  for invalid values.
- Config validators: model validation still flows through `CTFBaseModel.save()`
  and Django field choices. Tests should use model/service creation paths rather
  than bypassing choices with raw SQL or ad hoc factories that can encode
  impossible task states.
- Persistence and locking: due-task claiming uses
  `select_for_update(skip_locked=True)` and stale recovery uses conditional
  database updates. Unit tests can mock narrow pieces, but behavioral coverage
  should include database-backed assertions for durable row state.
- OS/runtime exposure: the scheduler heartbeat is
  `/tmp/ctf-scheduler-heartbeat`, and local/AWS/GCP startup contracts already
  reference that file. Do not add secret-bearing flags, per-host lock files, or
  a second host-level heartbeat for this traceability work.
- Error envelopes and leakage: scheduler exceptions may be logged and truncated
  into `CTFScheduledTask.error_message`; public API tests should continue to
  assert controlled CTF error messages and must not expose raw provider
  exceptions to participants or organizers.
- Observability: use existing module loggers. Assertions should prefer durable
  state and structured call boundaries over brittle full-message log snapshots.

## Extensibility Seam

The reusable seam is task-type-parametric scheduler coverage:

- a task creation/reschedule/cancel assertion pattern that can add future task
  types without re-copying the event scheduling matrix;
- a dispatcher assertion pattern that verifies a `ScheduledTaskType` is
  registered and calls its service boundary;
- deployment invariant tests that can accept future scheduler command flags only
  when those flags are non-secret settings-backed knobs.

Keep the seam at task type, schedule time, metadata, and service boundary. Do not
make tests depend on provider-specific payload shape, a single cloud topology, or
one fixed reminder interval list beyond the event's configured
`reminder_hours`.

## Gotchas

- `CTF-010` overlaps `CTF-1001` and concurrency issue #942, but its traceability
  link should point to tests proving scheduled event automation, not only
  platform process startup.
- `_schedule_event_tasks()` reads `event.reminder_hours` and filters invalid or
  past reminders. A test that assumes only `[24, 1]` will miss configurable
  reminders.
- `EVENT_END` can mark stale tasks cancelled when the event end has moved into
  the future. Do not treat every due `EVENT_END` row as a successful completion.
- `SPIN_UP_RANGES` is intentionally resumable and idempotent over participants
  without assigned ranges. A test that expects all interruptions to fail the task
  is asserting the wrong contract.
- The scheduler stores task failure text internally. Tests should not require
  exact raw exception strings except for bounded/sanitized behavior.
- SQLite can exercise most durable-state tests, but not all PostgreSQL lock
  semantics. Do not over-claim cross-node correctness from SQLite-only tests.
- Existing audit docs may describe older gaps. Prefer current code and current
  tests when selecting Ground Control `TESTS` links.

## Anti-Patterns

- Adding a Celery queue, cron table, in-memory queue, cache lock, or separate
  scheduler service to satisfy a test/traceability issue.
- Duplicating scheduler task schemas in serializers, fixtures, YAML, or Ground
  Control metadata.
- Testing scheduler behavior by patching private internals so deeply that no
  durable task row or service boundary is exercised.
- Treating deployment replica count as the scheduler correctness mechanism.
- Logging or storing raw cloud provider errors, email payloads, environment
  values, or invitation tokens while testing failure paths.
- Creating `TESTS` trace links to docs, factories, broad smoke tests, or test
  files that do not assert CTF-010 behavior.

## Non-Goals

- No scheduler redesign, platform scheduler replacement, or new automation
  infrastructure.
- No change to CTF event state-machine semantics, scoring, challenge visibility,
  notification template validation, CMS range contracts, or cloud provider
  deployment topology.
- No new public API surface for creating or executing scheduled tasks.
- No Ground Control `IMPLEMENTS` trace changes are required for this preflight;
  the upcoming work should add or reconcile `TESTS` links for maintained tests.
