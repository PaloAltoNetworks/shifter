---
id: CTF-1004
title: "Event Start/End Automation"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.856556Z
updated_at: 2026-04-04T22:15:12.663422Z
---

# CTF-1004: Event Start/End Automation

## Statement

The system should automatically transition event state at the configured start and end times. At start time, the event shall transition from registration to active (enabling flag submissions). At end time, the event shall transition from active to ended (disabling submissions and triggering cleanup). The system shall log automated transitions and notify organizers.

## Rationale

Manual event start/end requires an organizer to be online at the exact scheduled time, which is unreliable across timezones. Automated transitions ensure events start and end precisely when configured, maintaining fairness and consistency. (CTFd enforces time-based submission windows; Shifter should similarly automate the state transitions that enforce these windows.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py::_handle_event_start` (EVENT_START task handler - calls activate_event() to transition scheduled->active at configured start time)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py::_handle_event_end` (EVENT_END task handler - calls complete_event() to transition active->completed at configured end time)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py::activate_event,complete_event` (activate_event: scheduled->active transition. complete_event: active->completed transition. Both log transitions.)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py::_schedule_event_tasks(EVENT_START,EVENT_END)` (Schedules EVENT_START task at event_start time and EVENT_END task at event_end time when event is scheduled)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py::notify_organizer_event_start` (Sends organizer email notification when event automatically starts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py::notify_organizer_event_end` (Sends organizer email notification when event automatically ends)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/event_start.html` (HTML email template for event start organizer notification)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/event_end.html` (HTML email template for event end organizer notification)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_notification.py::TestNotifyOrganizerEventStart,TestNotifyOrganizerEventEnd` (Tests for organizer event start/end notification functions)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_scheduler_handlers.py::TestHandleEventStart,TestHandleEventEnd` (Tests for scheduler event start/end handlers with notification integration)
