---
id: CTF-1005
title: "Scheduled Reminders"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:23.895669Z
updated_at: 2026-04-05T18:26:31.188077Z
---

# CTF-1005: Scheduled Reminders

## Statement

The system could send automated reminder notifications at configurable intervals before event start (for example 24 hours, 1 hour before). Reminders shall be sent using the platform's email service (PLAT-103) to all registered participants who have not declined or been removed. The reminder content shall include event name, start time (in recipient's timezone), and access URL.

## Rationale

Participants who registered days ago may forget about the event. Reminders reduce no-show rates and ensure participants are prepared when the event starts. This is especially valuable for Shifter events where consultants have busy schedules and may have registered during a planning session weeks earlier.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py (send_reminder)` (send_reminder() service - sends reminder emails to registered participants)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py (schedule 24h reminder)` (Event service auto-schedules SEND_REMINDER task 24 hours before event start)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py (_handle_send_reminder)` (Scheduler handler for SEND_REMINDER - STUB, logs warning 'not yet implemented')
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_services/test_notification.py (TestSendReminder)` (Tests for send_reminder - verifies sends to registered participants)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py (reminder_hours, event_timezone fields)` (CTFEvent model - reminder_hours and event_timezone fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0023_add_reminder_hours.py` (Migration adding reminder_hours and event_timezone to CTFEvent)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/reminder.html` (Reminder HTML email template with access URL and timezone-aware start time)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/reminder.txt` (Reminder plain text email template with access URL and timezone-aware start time)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_scheduler_handlers.py (TestHandleSendReminder)` (Tests for _handle_send_reminder scheduler handler)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#582` (CTF-1005: Scheduled Reminders)
