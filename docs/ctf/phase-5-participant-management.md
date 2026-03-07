# Phase 5: Participant Management

## Overview

This phase implements the admin/organizer views and APIs for managing CTF event participants. The core models, services, and forms are already complete. This phase focuses on wiring up the views, templates, and APIs.

## Current State

### Completed
- `CTFParticipant` model with invite token, registration, team assignment
- `participant.py` service with: `invite_participant`, `bulk_import_participants`, `register_participant`, `get_participant_by_user`, `disqualify_participant`, `list_participants_for_event`, `get_participant`, `delete_participant`, `resend_invite`
- `CTFParticipantForm` and `CTFParticipantImportForm` forms
- URL routes defined in `urls.py`
- View stubs in `views.py` (return placeholder templates)
- Template files exist (placeholder content)

### Pending
- Implement `admin_participant_list` view
- Implement `admin_participant_import` view
- Implement `admin_participant_detail` view
- Implement API endpoints for participants
- Implement invite email sending (hooks into notification service)
- Complete template HTML

## Implementation Tasks

### 5.1 Admin Participant List View
**File:** `ctf/views.py` (line ~673)

```python
@login_required
@ctf_organizer_required
def admin_participant_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Participant list for an event with filtering and bulk actions."""
```

**Requirements:**
- Fetch event, verify organizer owns it
- Get participants using `list_participants_for_event(event_id)`
- Support filtering by status (query param `?status=invited|registered|active`)
- Display: name, email, status, team, registered_at, last_active_at
- Actions: resend invite, disqualify, delete
- Link to add participant / bulk import

**Template:** `ctf/admin/participant_list.html`

### 5.2 Admin Participant Import View
**File:** `ctf/views.py` (line ~690)

```python
@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_import(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Import participants from CSV."""
```

**Requirements:**
- GET: Show import form with `CTFParticipantImportForm`
- POST: Parse CSV, call `bulk_import_participants`
- Handle validation errors, show results
- Option to send invites immediately

**Template:** `ctf/admin/participant_import.html`

### 5.3 Admin Participant Detail View
**File:** `ctf/views.py` (line ~706)

```python
@login_required
@ctf_organizer_required
def admin_participant_detail(request: HttpRequest, participant_id: UUID) -> HttpResponse:
    """Participant detail view with submission history and actions."""
```

**Requirements:**
- Fetch participant using `get_participant(participant_id)`
- Verify organizer owns the event
- Display: full profile, registration info, team, range status
- Show submission history (solved challenges, scores)
- Actions: resend invite, change team, disqualify, delete

**Template:** `ctf/admin/participant_detail.html`

### 5.4 Add Single Participant View
**File:** `ctf/views.py` (new function)

```python
@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_add(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Add a single participant to an event."""
```

**Requirements:**
- GET: Show `CTFParticipantForm`
- POST: Validate and call `invite_participant`
- Option to send invite email immediately
- Redirect to participant list on success

**URL:** Add to `urls.py`: `path("admin/events/<uuid:event_id>/participants/add/", ...)`

### 5.5 API Endpoints

#### 5.5.1 Participant List API
**File:** `ctf/views.py` (line ~913)

```python
@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_participant_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
```

**GET Response:**
```json
{
  "participants": [
    {
      "id": "uuid",
      "name": "string",
      "email": "string",
      "status": "invited|registered|active|completed|disqualified",
      "team_name": "string|null",
      "registered_at": "iso8601|null",
      "total_score": 0
    }
  ],
  "total": 100
}
```

**POST Body:**
```json
{
  "email": "participant@example.com",
  "name": "Participant Name",
  "send_invite": true
}
```

#### 5.5.2 Participant Detail API
**File:** `ctf/views.py` (line ~941)

```python
@login_required
@ctf_organizer_required
@require_http_methods(["GET", "DELETE"])
def api_participant_detail(request: HttpRequest, participant_id: UUID) -> JsonResponse:
```

**GET Response:** Full participant object with submissions
**DELETE:** Soft delete participant

#### 5.5.3 Participant Import API
**File:** `ctf/views.py` (line ~928)

Already stubbed. Implement to accept CSV data and return import results.

#### 5.5.4 Resend Invite API
**File:** `ctf/views.py` (new function)

```python
@login_required
@ctf_organizer_required
@require_POST
def api_participant_resend_invite(request: HttpRequest, participant_id: UUID) -> JsonResponse:
```

Calls `resend_invite(participant_id)` and triggers email.

### 5.6 Template Implementation

#### participant_list.html
- Table with sortable columns
- Status filter dropdown
- Bulk action checkboxes
- HTMX for dynamic updates
- Export to CSV button

#### participant_import.html
- File upload form
- CSV format instructions
- Preview parsed data
- Error display
- Success summary

#### participant_detail.html
- Profile card with all fields
- Registration/invite status timeline
- Submission history table
- Score summary
- Action buttons (resend, disqualify, delete)

## Testing Requirements

### Unit Tests
- `test_participant_list_view`: Verify list rendering, filtering
- `test_participant_import_view`: Test CSV parsing, validation
- `test_participant_detail_view`: Verify detail display, permissions
- `test_api_participant_endpoints`: All CRUD operations

### Integration Tests
- Full flow: create event -> import participants -> send invites
- Verify permission checks (organizer can only see own events)
- Test bulk import with errors

## Dependencies

- Phase 4 complete (event/challenge management works)
- Notification service (Phase 7) for sending invite emails

## Estimated Effort

| Task | Hours |
|------|-------|
| 5.1 Participant List View | 3 |
| 5.2 Participant Import View | 3 |
| 5.3 Participant Detail View | 2 |
| 5.4 Add Participant View | 1 |
| 5.5 API Endpoints | 4 |
| 5.6 Templates | 4 |
| Testing | 4 |
| **Total** | **21** |
