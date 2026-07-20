# CTF Scheduler Concurrency Preflight (#942)

Status: pre-implementation guidance

Date: 2026-06-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/942>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Issue #942 is about scheduler correctness under the multi-node portal topology:
long-running `SPIN_UP_RANGES` work must not be marked stale while it is making
progress, and manual plus scheduled provisioning must not assign more than one
range to the same participant.

Keep these concepts separate:

1. Scheduler process liveness: `/tmp/ctf-scheduler-heartbeat` proves the
   management command poll loop is alive for Docker/Kubernetes probes.
2. Scheduled-task liveness: `CTFScheduledTask.updated_at` proves a claimed
   database task is still progressing and is the field stale recovery reads.
3. Scheduler election: only one portal node should execute the same global
   scheduling/provisioning critical section at a time.
4. Participant assignment atomicity: a participant's "already assigned" check and
   `range_instance_id` write must be protected by the same database lock.

Do not rely on AWS or GCP replica counts for correctness. AWS starts a scheduler
container on each portal EC2 instance, while GCP currently deploys one scheduler
replica; the persistence layer must still be the source of truth.

## Architecture Decisions

- Reuse the existing `CTFScheduledTask` row-locking discipline. `_fetch_due_tasks`
  already claims due work with `select_for_update(skip_locked=True)`; the fix
  should extend that database-coordination model instead of creating a parallel
  queue, in-memory mutex, file lock, cache lock, or scheduler service.
- Add an explicit scheduled-task heartbeat operation for long-running handlers.
  Heartbeating should update only the claimed task's `updated_at` and should be
  invoked from the throttled spin-up path at bounded intervals and before/after
  long sleeps.
- Make the stale threshold a settings-backed runtime parameter with a default
  above the maximum legitimate spin-up duration plus retry/scheduler jitter. Do
  not leave a hard-coded `30` minute threshold equal to the default
  `CTFEvent.range_spinup_minutes`.
- Use PostgreSQL-backed coordination for cross-node election. A transaction-scoped
  advisory lock is acceptable for the scheduler's global spin-up critical section
  if the implementation keeps the lock key stable, documented, non-secret, and
  non-blocking for ordinary task polling. If a row-claim design is used instead,
  keep it on `CTFScheduledTask` or `CTFEvent`; do not add a new leader model
  unless the existing rows cannot express the lease safely.
- Protect participant assignment in `ctf.services.range.provision_participant_range`
  with `transaction.atomic()` plus `CTFParticipant.objects.select_for_update()`.
  The lock must cover the "registered user", "already assigned", CMS create call,
  range-instance lookup, and participant write unless the implementation can
  prove a shorter lock still prevents double assignment.
- Preserve the `ctf.bridges` boundary for CMS interactions. Scheduler and CTF
  services should not import CMS models directly or duplicate range-provisioning
  workflow logic.
- Treat "already assigned" as a benign race loser where appropriate. A second
  scheduler/manual caller that finds an assigned participant after acquiring the
  row lock should not create a second range and should not poison the whole event
  spin-up as a provisioning failure.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #942 |
| --- | --- | --- |
| Scheduled tasks | `ctf.models.CTFScheduledTask`, `ctf.enums.ScheduledTaskStatus`, `run_ctf_scheduler.py` | Extend `mark_running`/heartbeat/stale-recovery semantics; do not add a second task table or task status enum. |
| Task claiming | `Command._fetch_due_tasks()` in `ctf/management/commands/run_ctf_scheduler.py` | Keep `select_for_update(skip_locked=True)` as the claim pattern for due rows. |
| Long-running spin-up | `ctf.services.range.provision_event_ranges_throttled()` | Add heartbeat hooks/parameters here; do not duplicate the throttled loop in the scheduler command. |
| Participant assignment | `ctf.services.range.provision_participant_range()` | Lock the participant row around assignment and CMS provisioning; keep validation and exception behavior local to the service. |
| CMS integration | `ctf.bridges` | All range create/status/destroy calls cross through the bridge module. |
| CTF errors | `ctf.exceptions.CTFRangeError`, `CTFNotFoundError` | Reuse the hierarchy and authored messages; do not introduce scheduler-specific public exception classes. |
| Timestamps and validation | `CTFBaseModel.save()`, model `full_clean()` | Heartbeat with a targeted `update()` or targeted save that keeps model validation expectations intact. |
| Runtime settings | `config.settings._env_int`, Terraform/SSM env binding | New thresholds bind through settings/env, with tests for invalid values if a new env knob is added. |
| Logging hygiene | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()` | Logs may include task id, event id, participant id, counts, timings, and lock outcomes; no env dumps, DB URLs, user email bodies, or provider payloads. |
| Deployment topology tests | `tests/platform/test_ctf_scheduler_startup.py`, AWS `user_data.sh`, GCP `ctf-scheduler-deployment.yaml`, Helm chart | Do not change replica/deploy topology as the primary fix; update tests only if launch/probe contracts change. |

## Cross-Cutting Layers

- Auth surface: manual provisioning remains behind the existing organizer view/API
  checks in `ctf.views`; scheduled provisioning runs as the management command.
  The service-layer lock must not weaken view authorization or create a direct
  unauthenticated provisioning path.
- Secret-handling surface: the design should not add secrets. Advisory lock keys,
  stale thresholds, heartbeat intervals, task ids, event ids, and participant ids
  are non-secret. Do not pass database URLs, cloud credentials, invite tokens, or
  range credentials in argv, metadata, logs, or `error_message`.
- Env-binding shape: stale-window and heartbeat cadence, if configurable, belong
  in `config.settings` using the existing `_env_int` parser and are supplied by
  the portal runtime env/SSM/Terraform path. Avoid per-node local files or
  environment-specific constants in scheduler code.
- Config validators: a new setting must fail loud on invalid integer input and
  should enforce positive/minimum relationships in Python tests. Terraform/SSM
  wiring, if touched, must carry matching numeric validation.
- Persistence: production correctness depends on PostgreSQL row locks/advisory
  locks. Unit tests may mock ORM calls, but at least one transactional test should
  exercise the no-double-assignment path under the database backend available to
  CI and should skip or isolate PostgreSQL-only advisory-lock behavior when CI is
  SQLite.
- OS/runtime exposure: no new process manager, shell wrapper, or host lock file is
  needed. If command-line flags are added for local testing, keep them
  non-secret and bounded integers only.
- Error envelopes: public/manual API responses should keep the existing CTF error
  shape and fixed user-facing messages. Scheduler internals may store sanitized,
  truncated failure text in `CTFScheduledTask.error_message`, but stale recovery
  must not overwrite an actively heartbeating task.
- Observability: use existing module loggers with structured, low-cardinality
  fields. Log lock not-acquired/race-loser paths at info/debug, stale recovery at
  warning, and actual provisioning failures at error/exception.

## Extensibility Seam

The seam is a small scheduler coordination policy:

- stale timeout: one setting above legitimate spin-up duration;
- heartbeat cadence: one bounded interval used by long-running handlers;
- election/lock name: stable per critical section, with room for future task-type
  keys if cleanup or challenge release later needs the same protection;
- assignment lock: participant-row critical section that can later cover team- or
  event-level allocation without changing the CMS bridge contract.

This keeps future scheduler work from editing deployment topology or copying the
range provisioning loop.

## Gotchas

- `updated_at` is inherited from `CTFBaseModel` and currently changes only when a
  task status is saved. A long sleep inside the throttled loop will look stale
  unless the task itself is heartbeated.
- The default `range_spinup_minutes` is `30`; any stale timeout equal to 30
  minutes has no retry/polling margin.
- `skip_locked=True` prevents two processes from claiming the same pending task,
  but it does not prevent one process from marking another process's already
  claimed long-running task stale.
- PostgreSQL advisory locks are connection/transaction scoped. Do not hold a
  transaction-scoped advisory lock accidentally past the intended critical
  section, and do not assume SQLite exercises the same behavior.
- Holding a participant row lock across a cloud/CMS create call can serialize
  concurrent manual/scheduled attempts for that participant. That is acceptable
  for correctness; do not widen it to an event-wide lock unless election requires
  it.
- If the loser of a race sees `range_instance_id` set, it should not retry CMS
  provisioning. Retrying "already assigned" defeats the lock.
- `CTFBaseModel.save()` calls `full_clean()`. A heartbeat should avoid unrelated
  field mutations and should not require loading/validating an entire event graph
  on every tick.

## Anti-Patterns

- Increasing the stale timeout only, without heartbeating the running task.
- Disabling stale recovery entirely.
- Making AWS `asg_desired_capacity = 1` or GCP replicas the correctness fix.
- Using process-local globals, files under `/tmp`, Redis cache locks, or Docker
  container names for cross-node scheduler election.
- Importing CMS models directly from scheduler code or duplicating
  `ctf.bridges` range calls.
- Adding duplicate scheduler task DTOs, validation schemas, status enums, or
  exception hierarchies.
- Logging raw exception strings into participant-visible responses or storing
  secret-bearing provider payloads in scheduled-task metadata.

## Non-Goals

- No redesign of event scheduling, challenge release, notifications, CTF scoring,
  CMS range lifecycle, or the worker/SQS system.
- No portal deployment topology change unless a separate issue accepts that
  operational tradeoff.
- No new durable leader-election table unless `CTFScheduledTask`/`CTFEvent` rows
  and PostgreSQL advisory locks are insufficient.
- No formal Ground Control requirement or traceability update is needed for this
  requirement-free issue.
