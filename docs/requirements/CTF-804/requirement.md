---
id: CTF-804
title: "Scheduled Notifications"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:23.392764Z
updated_at: 2026-03-19T03:08:17.951432Z
---

# CTF-804: Scheduled Notifications

## Statement

The system could support scheduling notifications for future delivery at a specified date and time. Scheduled notifications shall support the same content as announcements. The scheduler shall process notifications within one minute of the configured time. Organizers shall be able to cancel scheduled notifications before delivery.

## Rationale

Scheduled notifications enable organizers to plan communications in advance, event reminders the day before, mid-event encouragement, or time-remaining warnings. Without scheduling, organizers must be online at the exact moment to send communications, which is unreliable for events that span multiple timezones.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py (CTFNotification.scheduled_at)` (CTFNotification model with scheduled_at field and SCHEDULED status)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py (schedule_notification)` (schedule_notification() service - schedules notification and creates CTFScheduledTask)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py (admin_notification_form - schedule action)` (Notification form view with schedule action and scheduled_at parsing)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` (CTF scheduler - polls every 30 seconds, but SEND_REMINDER handler is stub (not implemented))
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_services/test_notification.py (TestScheduleNotification)` (Tests for schedule_notification - verifies status and scheduled task creation)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#667` (CTF-804: Scheduled Notifications)
