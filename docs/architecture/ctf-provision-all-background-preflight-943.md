# CTF Provision-All Background Preflight (#943)

Status: pre-implementation guidance

Date: 2026-06-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/943>

## Scope Boundary

Issue #943 moves the organizer "Provision All Ranges" action off the Django
request thread. It is requirement-free; the GitHub issue is the source of
truth.

The change should make the organizer API enqueue or advance existing CTF
scheduler work, return immediately, and let the scheduler run the throttled
range-provisioning loop with visible progress. It is not a new queueing system,
range lifecycle rewrite, CMS/Engine schema change, or cloud provisioner
redesign.

## Architecture Decisions

- The organizer POST path must authenticate, authorize event ownership, enqueue
  or coalesce one due `SPIN_UP_RANGES` scheduled task, and return a small JSON
  envelope immediately. It must not call `provision_event_ranges`,
  `provision_event_ranges_throttled`, or `provision_participant_range_with_retry`
  from the request thread.
- Reuse `CTFScheduledTask` and `run_ctf_scheduler` as the background task
  infrastructure. Manual provision-all should be represented as the same
  domain action as scheduled spin-up, with metadata such as source/requesting
  organizer only if useful for audit or UI.
- Coalesce duplicate clicks and pre-existing scheduled spin-up work per event.
  A pending or running `SPIN_UP_RANGES` task should be visible as queued or
  running progress, not duplicated into concurrent runnable tasks.
- Keep queue state and range state separate. `CTFScheduledTask.status` describes
  background work; `CTFParticipant.range_status` mirrors CMS/Engine range
  lifecycle. "Queued" is a UI/progress projection unless the domain explicitly
  accepts a new participant range status.
- Progress should be computed from existing state: participant range-status
  aggregation plus the relevant scheduled-task status. Add a small CTF service
  helper for this projection if needed; do not add a duplicate progress table
  or client-side schema.
- The scheduler must remain live during long provisioning loops. Long-running
  range work needs a scheduler heartbeat/progress callback or equivalent so the
  existing Docker/Kubernetes heartbeat checks do not restart the scheduler
  mid-loop.
- Interruption must not be recorded as successful completion. If
  `provision_event_ranges_throttled` exits with `interrupted=True`, the task
  handler must leave work recoverable or failed in a way that a later enqueue can
  safely continue unassigned participants.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #943 |
| --- | --- | --- |
| Organizer auth | `@login_required`, `@ctf_organizer_required`, event `created_by_id` checks in `ctf.views` | Preserve all gates for enqueue and progress endpoints. |
| Background task record | `ctf.models.CTFScheduledTask`, `ScheduledTaskType.SPIN_UP_RANGES`, `ScheduledTaskStatus` | Reuse this table/status model; do not introduce Celery, RQ, ad hoc threads, or a second queue. |
| Scheduler execution | `ctf.management.commands.run_ctf_scheduler` | Keep `select_for_update(skip_locked)`, single-replica assumptions, stale-task recovery, signal handling, and heartbeat semantics. |
| Throttled provisioning | `ctf.services.range.provision_event_ranges_throttled` | This remains scheduler-owned work; request handlers only enqueue and report progress. |
| Participant provisioning | `ctf.services.range.provision_participant_range` and `provision_participant_range_with_retry` | Reuse CTF range service and retry/error behavior; do not call CMS or Engine directly from views. |
| CMS boundary | `ctf.bridges.cms_create_range`, `cms_find_range_instance_id`, `cms_get_range_status` | Keep cross-domain calls behind the bridge; do not query CMS/Engine internals from CTF views or JavaScript. |
| CMS/Engine validation | `cms.services.create_range`, `RangeContext`, `RequestSpec`, `shared.enums.ResourceStatus` | Preserve scenario, agent, ownership, active-range, request-id, and status validation. |
| Range progress UI | `api_range_list`, `admin_dashboard` status aggregation, `static/js/ctf-ranges.js` | Extend existing polling/progress surfaces instead of creating unrelated endpoints or schemas. |
| Status sync | `cms.handlers.range_events`, `ctf.signals.sync_ctf_participant_range_status` | Let CMS/Engine events update participant `range_status`; do not hand-roll status transitions in the UI. |
| Logging hygiene | `shared.log_sanitize.safe_log_value`, module loggers | Log event/task IDs, counts, durations, and statuses only; sanitize user-controlled or external values. |
| Runtime deployment | local compose, AWS Docker deploy scripts, GCP manifests, Helm chart, stack-smoke, worker-health tests | If scheduler command/env/probe semantics change, update every runtime surface and invariant test together. |

## Cross-Cutting Layers

- Auth surface: organizer enqueue and progress APIs must keep session auth,
  CSRF-protected POST for mutation, `@ctf_organizer_required`, and per-event
  owner checks. Polling can be GET, but it still needs organizer and event-owner
  authorization.
- Validation surface: the URL `event_id` is the only required request input.
  If a future override is added for window or pacing, bind it through typed
  settings or the validated `CTFEvent.range_spinup_minutes` model field, not raw
  JSON values accepted by the view.
- Service boundary: CTF views delegate to CTF services; CTF services cross into
  CMS only through `ctf.bridges`; CMS continues to own scenario hydration,
  active-range checks, `RequestSpec` creation, and `RangeContext` shape.
- Secret-handling surface: this flow should not materialize secrets. It must not
  log or return agents, scenario internals, request payloads, queue URLs, SQS
  endpoints, cloud task ARNs, secret references, or process environments.
- Config shape: new scheduler/progress knobs, if truly needed, belong in typed
  Django settings and the existing runtime env binding surfaces. Do not bury
  magic delay, poll, or stale thresholds in views or JavaScript.
- OS/process exposure: do not pass event IDs, organizer emails, secrets, or JSON
  payloads through shell command lines or process argv. The existing scheduler
  process should remain `python manage.py run_ctf_scheduler` with environment
  owned by deployment config.
- Error-envelope surface: clients should receive bounded JSON such as queued
  task id/status and aggregate counts, or generic `error` messages. Raw
  exception text, task `error_message`, stack traces, CMS errors, and cloud
  provider messages stay server-side.
- Observability surface: useful signal is queued/running/completed/failed task
  state, ready/provisioning/error/not-assigned counts, task duration,
  interruption, retries exhausted, and coalesced duplicate clicks. Keep metrics
  or log labels low-cardinality.
- Runtime health surface: scheduler liveness remains the heartbeat file consumed
  by Docker/Kubernetes and stack-smoke. Do not move scheduler health into portal
  `/health` or rely on a blocked request to prove progress.

## Extensibility Seam

The durable seam is a CTF-local "manual spin-up enqueue plus progress
projection" around `CTFScheduledTask`:

- enqueue parameters: `event_id`, requesting organizer id, due time, source
  (`manual` versus scheduled), and optional idempotency/coalescing behavior;
- execution parameters: the event's validated `range_spinup_minutes` converted
  to the scheduler's throttling window, plus a heartbeat/progress callback;
- progress projection: task status, task timestamps, and participant
  ready/provisioning/error/not-assigned counts returned through one existing
  organizer progress endpoint.

That seam lets future manual retries, cancel/requeue, scheduler-only progress
refresh, or alternate pacing policies extend the same task contract without
rewriting views, JavaScript, or deployment wiring.

## Gotchas And Anti-Patterns

- Do not "fix" the timeout by spawning a Python thread from the gunicorn worker.
  A worker restart would still orphan process-local state.
- Do not add Celery/RQ/SQS for this issue; the CTF scheduler already exists and
  is deployed across local, AWS, and GCP paths.
- Do not call the throttled service from the API view just because it is already
  slower-paced. It still sleeps and still blocks gunicorn.
- Do not confuse a queued background task with participant range status.
  Overloading `CTFParticipant.range_status` with task states will leak queue
  implementation into CMS/Engine range lifecycle semantics.
- Do not create duplicate `SPIN_UP_RANGES` tasks for repeated clicks. Duplicate
  runnable tasks can race participant provisioning even if individual range
  creation has active-range checks.
- Do not leave the original future scheduled spin-up task intact if a manual
  due-now task supersedes it; it can re-run unexpectedly at event start.
- Do not mark interrupted throttled work completed. Existing unassigned
  participants make rerun mostly idempotent only if the task state remains
  recoverable.
- Do not rely on the scheduler's existing per-poll heartbeat for large events.
  A long handler can make the heartbeat stale before the poll cycle returns.
- Do not expose `task.error_message` or collected per-participant raw exception
  strings directly in the browser. Summarize for organizers and log details
  server-side.
- Do not query CMS or Engine tables from CTF JavaScript or CTF views to compute
  progress. Use the CTF participant cache and service boundary.

## Non-Goals

- No implementation is performed by this preflight.
- No redesign of range provisioning, CMS scenario hydration, Engine request
  schemas, provider task launch, range event messages, or SNS/SQS handlers.
- No new participant range actions are required beyond organizer provision-all.
- No migration to a different background-worker framework.
- No new formal Ground Control requirement is attached; issue #943 remains the
  contract.
- No weakening of CSRF, organizer authorization, import-linter, ADR guard,
  secret scanning, runtime health probes, Terraform checks, or Kubernetes
  policy checks.

## Validation

At minimum, architecture or `shifter/shifter_platform` changes on this path must
run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups should also run targeted CTF range/scheduler/API/JS
tests and the platform scheduler-startup invariants when deployment, command,
heartbeat, or env surfaces change.
