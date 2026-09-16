---
id: CTF-1001
title: "Scheduled Task Framework"
status: ACTIVE
type: CONSTRAINT
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.731635Z
updated_at: 2026-03-26T06:11:10.779892Z
---

# CTF-1001: Scheduled Task Framework

## Statement

CTF scheduled tasks (range spinup, cleanup, event transitions, reminders) shall be registered as task types within the existing platform scheduler framework. The CTF scheduler management command polls for due tasks and dispatches them to CTF-specific handlers. Task types include: SPIN_UP_RANGES, CLEANUP_RANGES, EVENT_START, EVENT_END, SEND_REMINDER. The framework supports task status tracking (pending, running, completed, failed), stale task recovery, and graceful shutdown. The CTF layer shall not build a separate scheduling infrastructure.

## Rationale

Multiple CTF automation features (range spinup, cleanup, event transitions, reminders) all need scheduled execution. A shared framework avoids reimplementing scheduling logic for each feature. The existing Shifter scheduler provides a foundation, but CTF tasks have different lifecycle requirements tied to event state.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py::CTFScheduledTask` (CTFScheduledTask model - task_type, scheduled_for, status tracking (pending/running/completed/failed), error_message, mark_running/mark_completed/mark_failed/mark_cancelled methods)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` (run_ctf_scheduler management command - poll loop, signal handling, heartbeat, atomic task claiming (select_for_update/skip_locked), stale recovery, task dispatch)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py::ScheduledTaskType,ScheduledTaskStatus` (ScheduledTaskType enum (SPIN_UP_RANGES, CLEANUP_RANGES, SEND_REMINDER, EVENT_START, EVENT_END) and ScheduledTaskStatus enum (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py::_schedule_event_tasks,_reschedule_event_tasks,_cancel_event_tasks` (Event task scheduling helpers - create/reschedule/cancel scheduled tasks tied to event lifecycle)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_scheduler_handlers.py` (CTF scheduler handler tests - framework task claiming, dispatch, stale recovery, graceful handler outcomes)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
