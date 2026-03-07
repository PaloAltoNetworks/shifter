# Phase 7: Range Integration & Notifications

## Overview

This phase integrates the CTF module with Shifter's range provisioning system and implements the email notification system. These are the final components needed for a fully functional CTF platform.

## Current State

### Completed
- `CTFScheduledTask` model for task scheduling
- `notification.py` service stubs (send_invitations, send_credentials, send_reminder, send_announcement)
- `CTFNotification` model with scheduling support
- `range.py` service file (exists but minimal)
- Admin notification views (stubs)
- Participant range view (stub)

### Pending
- Range provisioning integration
- Range status polling/updates
- Email sending implementation (SES)
- Scheduled task execution (Celery)
- Admin notification management views
- Invite email templates

## Implementation Tasks

### 7.1 Range Service Integration
**File:** `ctf/services/range.py`

```python
"""CTF Range service - Integration with Shifter range provisioning."""

def provision_participant_range(participant_id: UUID) -> dict:
    """Provision a range instance for a participant."""

def get_range_status(participant_id: UUID) -> dict:
    """Get current range status for a participant."""

def get_range_access_url(participant_id: UUID) -> str:
    """Get Guacamole access URL for participant's range."""

def destroy_participant_range(participant_id: UUID) -> bool:
    """Destroy a participant's range instance."""

def provision_event_ranges(event_id: UUID) -> dict:
    """Provision ranges for all participants in an event."""

def destroy_event_ranges(event_id: UUID) -> dict:
    """Destroy all ranges for an event (cleanup)."""
```

**Integration Points:**
- CMS `RangeInstance` model for range tracking
- Provisioner service for AWS orchestration
- Guacamole for remote access

### 7.2 Range Status Updates
**File:** `ctf/services/range.py`

```python
def update_participant_range_status(participant_id: UUID) -> CTFParticipant:
    """Poll and update cached range status for a participant."""
```

**Status Values:**
- `not_assigned` - No range requested yet
- `provisioning` - Range being created
- `ready` - Range available for use
- `error` - Provisioning failed
- `destroying` - Range being cleaned up
- `destroyed` - Range has been removed

### 7.3 Range API Endpoints
**File:** `ctf/views.py`

```python
@login_required
@require_GET
def api_range_status(request: HttpRequest) -> JsonResponse:
    """API: Get range status for current participant."""
```

**Response:**
```json
{
  "status": "ready",
  "access_url": "https://guacamole.example.com/...",
  "credentials": {
    "username": "ctf-user",
    "password": "generated-password"
  },
  "provisioned_at": "2024-01-15T10:00:00Z",
  "expires_at": "2024-01-15T18:00:00Z"
}
```

```python
@login_required
@require_POST
def api_range_access(request: HttpRequest) -> JsonResponse:
    """API: Get or refresh range access URL."""
```

### 7.4 Scheduled Task Execution
**File:** `ctf/tasks.py` (new file)

```python
"""CTF Celery tasks for scheduled operations."""

from celery import shared_task

@shared_task
def process_scheduled_tasks():
    """Process due CTF scheduled tasks."""

@shared_task
def provision_event_ranges(event_id: str):
    """Provision ranges for an event (pre-event spinup)."""

@shared_task
def cleanup_event_ranges(event_id: str):
    """Clean up ranges after event ends."""

@shared_task
def send_scheduled_notification(notification_id: str):
    """Send a scheduled notification."""

@shared_task
def activate_event(event_id: str):
    """Auto-activate event at scheduled start time."""

@shared_task
def complete_event(event_id: str):
    """Auto-complete event at scheduled end time."""
```

### 7.5 Task Scheduler Integration
**File:** `ctf/services/event.py` - enhance `_schedule_event_tasks`

```python
def _schedule_event_tasks(event: CTFEvent) -> None:
    """Schedule automated tasks for an event."""
    from ctf.models import CTFScheduledTask
    from ctf.enums import ScheduledTaskType

    # Create scheduled tasks
    tasks = [
        (ScheduledTaskType.RANGE_PROVISION, event.get_spinup_time()),
        (ScheduledTaskType.EVENT_START, event.event_start),
        (ScheduledTaskType.EVENT_END, event.event_end),
        (ScheduledTaskType.RANGE_CLEANUP, event.get_cleanup_time()),
    ]

    for task_type, scheduled_for in tasks:
        CTFScheduledTask.objects.create(
            event=event,
            task_type=task_type.value,
            scheduled_for=scheduled_for,
        )
```

### 7.6 Email Notification Implementation
**File:** `ctf/services/notification.py` - implement stubs

```python
def _send_email(to_email: str, subject: str, body: str, html_body: str = None) -> bool:
    """Send email via Django email backend (SES)."""
    from django.core.mail import send_mail
    from django.conf import settings

    return send_mail(
        subject=subject,
        message=body,
        from_email=settings.CTF_FROM_EMAIL,
        recipient_list=[to_email],
        html_message=html_body,
        fail_silently=False,
    )

def send_invitations(event_id: UUID) -> dict:
    """Send invitation emails to all invited participants."""
    # Implementation with actual email sending

def send_credentials(event_id: UUID) -> dict:
    """Send credential emails to participants with ready ranges."""
    # Implementation
```

### 7.7 Email Templates
**Directory:** `ctf/templates/ctf/email/`

Create email templates:
- `invite.html` - Invitation email with registration link
- `invite.txt` - Plain text version
- `credentials.html` - Range access credentials
- `credentials.txt`
- `reminder.html` - Event reminder
- `reminder.txt`
- `announcement.html` - Custom announcements
- `announcement.txt`

**Template Context Variables:**
```python
{
    "participant_name": "John Doe",
    "event_name": "CTF Challenge 2024",
    "event_start": datetime,
    "event_end": datetime,
    "registration_url": "https://...",
    "invite_expires": datetime,
    "range_url": "https://...",
    "credentials": {...},
}
```

### 7.8 Admin Notification Views
**File:** `ctf/views.py`

```python
@login_required
@ctf_organizer_required
def admin_notification_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Notification list for an event."""
    # Show sent, scheduled, and draft notifications

@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_notification_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new notification."""
    # Form to compose notification
    # Options: send now, schedule, save draft
```

### 7.9 Admin Range Management Views
**File:** `ctf/views.py`

```python
@login_required
@ctf_organizer_required
def admin_range_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Range status overview for an event."""
```

**Features:**
- List all participants with range status
- Bulk provision button
- Individual range actions (provision, destroy, refresh)
- Status summary (ready, provisioning, error counts)

### 7.10 Range List API
**File:** `ctf/views.py` (new)

```python
@login_required
@ctf_organizer_required
@require_GET
def api_range_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get range status for all participants."""

@login_required
@ctf_organizer_required
@require_POST
def api_provision_ranges(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Trigger range provisioning for event."""
```

### 7.11 Notification APIs
**File:** `ctf/views.py`

```python
@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_notification_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List or create notifications."""

@login_required
@ctf_organizer_required
@require_POST
def api_notification_send(request: HttpRequest, notification_id: UUID) -> JsonResponse:
    """API: Send a notification immediately."""
```

## Templates

### admin/range_list.html
- Participant range status table
- Provision all button
- Individual row actions
- Status filter
- Error details modal

### admin/notification_list.html
- Notification cards with status
- Draft, scheduled, sent sections
- Quick compose button
- Schedule calendar view

### admin/notification_form.html
- Subject and body editor (Markdown)
- Recipient filter (all, registered, teams)
- Send now / schedule / save draft buttons
- Preview option

### email/*.html
- Branded email templates
- Responsive design
- Clear call-to-action buttons
- Unsubscribe link (compliance)

## Configuration

### Django Settings
```python
# Email (SES)
CTF_FROM_EMAIL = "ctf@shifter.example.com"
EMAIL_BACKEND = "django_ses.SESBackend"
AWS_SES_REGION_NAME = "us-east-2"
AWS_SES_REGION_ENDPOINT = "email.us-east-2.amazonaws.com"

# CTF Range Settings
CTF_DEFAULT_RANGE_SPINUP_MINUTES = 30
CTF_DEFAULT_CLEANUP_DELAY_HOURS = 24
CTF_RANGE_SCENARIO_ID = "ctf-basic"
```

### Celery Beat Schedule
```python
CELERY_BEAT_SCHEDULE = {
    "process-ctf-scheduled-tasks": {
        "task": "ctf.tasks.process_scheduled_tasks",
        "schedule": 60.0,  # Every minute
    },
}
```

## Testing Requirements

### Unit Tests
- `test_range_provisioning`: Mock provisioner, verify status updates
- `test_range_status_polling`: Status transitions
- `test_email_sending`: Mock SES, verify templates
- `test_scheduled_tasks`: Task creation and execution
- `test_notification_apis`: CRUD operations

### Integration Tests
- Full range lifecycle: provision -> access -> destroy
- Notification flow: create -> schedule -> send
- Event lifecycle with automated tasks

## Security Considerations

- Rate limit range provisioning requests
- Validate participant owns requested range
- Encrypt credentials in transit
- Audit log all range operations
- Verify email recipients are event participants

## Dependencies

- Phases 5-6 complete
- Shifter CMS range models
- Provisioner service running
- Celery worker running
- SES configured and verified

## Estimated Effort

| Task | Hours |
|------|-------|
| 7.1-7.2 Range Service | 8 |
| 7.3 Range APIs | 3 |
| 7.4-7.5 Scheduled Tasks | 6 |
| 7.6 Email Implementation | 4 |
| 7.7 Email Templates | 4 |
| 7.8-7.9 Admin Views | 4 |
| 7.10-7.11 APIs | 3 |
| Templates | 4 |
| Configuration | 2 |
| Testing | 8 |
| **Total** | **46** |

## Phase Completion Criteria

- [ ] Ranges can be provisioned for participants
- [ ] Participants can access their range via Guacamole
- [ ] Invitation emails are sent with valid registration links
- [ ] Credential emails are sent when ranges are ready
- [ ] Event auto-starts and auto-ends on schedule
- [ ] Ranges are cleaned up after event ends
- [ ] Organizers can send custom announcements
- [ ] All scheduled tasks execute reliably
