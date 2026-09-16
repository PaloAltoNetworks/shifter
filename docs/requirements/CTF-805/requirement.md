---
id: CTF-805
title: "Email Templates"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.425637Z
updated_at: 2026-04-05T04:08:45.281370Z
---

# CTF-805: Email Templates

## Statement

CTF email notifications shall use the platform's email templating and delivery service (PLAT-103). Default templates shall be provided for all CTF notification types (invitation, credentials, reminder, announcement, provisioning failure). Organizers could optionally customize templates per event. Template variables shall include participant name, event name, event URL, and dates.

## Rationale

Email delivery is a platform capability. CTF defines its notification types and templates but delegates rendering and delivery to PLAT-103 rather than implementing its own email pipeline.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py` (CTF Notification Service)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/invitation.html` (Invitation Email Template (HTML))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/invitation.txt` (Invitation Email Template (Text))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/credentials.html` (Credentials Email Template (HTML))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/credentials.txt` (Credentials Email Template (Text))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/reminder.html` (Reminder Email Template (HTML))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/reminder.txt` (Reminder Email Template (Text))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/announcement.html` (Announcement Email Template (HTML))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/announcement.txt` (Announcement Email Template (Text))
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_services/test_notification.py` (Notification Service Tests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/provision_failure.html` (Provisioning Failure Email Template (HTML))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/provision_failure.txt` (Provisioning Failure Email Template (Text))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py (CTFEmailTemplate)` (CTFEmailTemplate model for per-event email template overrides)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py (admin_event_email_templates, api_event_email_template)` (Admin view and API endpoint for managing per-event email templates)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0022_add_email_template.py` (Migration creating CTFEmailTemplate table)
