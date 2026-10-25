---
id: CTF-010
title: "Scheduled Tasks & Automation"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.230446Z
updated_at: 2026-03-26T06:33:55.418204Z
---

# CTF-010: Scheduled Tasks & Automation

## Statement

The CTF layer should automate time-sensitive event operations, such as range provisioning, resource cleanup, and state transitions, using the platform's scheduler framework (see CTF-1001). Events run reliably without requiring organizer presence at exact moments.

## Rationale

CTF events have time-bound lifecycles that require actions at specific moments, ranges must be ready before start, torn down after end, reminders sent in advance. Manual execution is error-prone and requires organizer availability at exact times. CTF registers its task types with the platform scheduler rather than building its own automation infrastructure.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py (CTFScheduledTask)` (CTFScheduledTask model (task_type, scheduled_for, status, mark_running/completed/failed/cancelled))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` (CTF scheduler management command (poll loop, signal handling, heartbeat, stale task recovery, task dispatch))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py (_schedule_event_tasks, _reschedule_event_tasks, _cancel_event_tasks)` (Event task scheduling: spin_up_ranges, event_start, event_end, cleanup_ranges, send_reminder)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py (ScheduledTaskType, ScheduledTaskStatus)` (Scheduled task enums: SPIN_UP_RANGES, CLEANUP_RANGES, SEND_REMINDER, EVENT_START, EVENT_END + status lifecycle)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_scheduler_handlers.py` (CTF scheduler handler tests - task dispatch, lifecycle handlers, stale recovery, reminders, release and cleanup)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_reconcile_range_events.py` (Canonical reconciler lease-expiry tests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/management/commands/reconcile_range_events.py` (Canonical range event and lease reconciliation runtime)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_range_lease.py` (Server-owned range lease and expiry lifecycle)
- IMPLEMENTS → GITHUB_ISSUE `2099` (Issue #2099 - unified communication admission + scheduler due-time integration (slice 2 of #2049))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/admission.py` (One admission owner: live actor/token/workspace/event re-authorization inside the release transaction; token-authored fail-closed; source-realizability policy (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/scheduling.py` (Scheduled declaration + task committed together; due-time release re-entering admission; grace/EXPIRED lateness policy; authorized run-now early release (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/release.py` (One admission transaction: event-first primary-key lock order, live target-event lock, nested-savepoint uniqueness-race handling, due-time release (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/lifecycle.py` (Cancellation/participant-removal/event-cancellation/range-replacement fences (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/notification.py (CTFScheduledTask)` (Claim-token completion/requeue/reschedule fences and stale-recovery-within-budget for scheduler tasks (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event/scheduling.py (run_task_now)` (Communication run-now routed through authorized early release, not a silent make-due (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/communication_contracts.py` (Trigger UTC/status/reference/type + audience cardinality bounds (#2099))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/_ctf_communication_settings.py` (CTF_COMMUNICATION_RELEASE_GRACE_MINUTES lateness/expiry policy (#2099))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_admission.py` (Live re-authorization denials, token fail-closed, system admission (#2099))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_scheduling.py` (Schedule/due-release idempotency, grace/EXPIRED, authorized early release, run-now (#2099))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_sources.py` (Source realizability: fail-closed RAES/range-signal, realizable manual/absolute-time (#2099))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_lifecycle_wiring.py` (Event cancel / participant delete / account purge fire the communication fences (#2099))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_scheduler_claim_fence.py` (Claim-fenced completion/requeue/cancel mutual exclusion (#2099))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_admission_postgres.py` (PostgreSQL races: concurrent due release idempotency, release-vs-cancel, single-claim, stale-worker fence (#2099))
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/operation_policy.py` (ADR-066 S5 classification of intrinsic, reauthorized, and retired scheduled effects)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_authorization_operation_map.py` (Scheduled-task classification covers every dispatched task type)
