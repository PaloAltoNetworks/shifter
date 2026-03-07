# CTF Management Platform - Implementation Plan

## Overview

The CTF Management Platform is a module within Shifter that enables organizers to create and run Capture The Flag competitions. It integrates with Shifter's range provisioning, authentication, and notification systems.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CTF Module                                │
├─────────────────┬─────────────────┬─────────────────────────────┤
│   Admin Portal  │ Participant     │        API Layer            │
│   (Organizers)  │ Portal          │  (JSON endpoints)           │
├─────────────────┴─────────────────┴─────────────────────────────┤
│                       Views (views.py)                          │
├─────────────────┬─────────────────┬─────────────────────────────┤
│ Event Service   │ Challenge       │ Participant    │ Scoring    │
│                 │ Service         │ Service        │ Service    │
├─────────────────┴─────────────────┴─────────────────────────────┤
│                       Models (models.py)                        │
│  CTFEvent | CTFChallenge | CTFParticipant | CTFSubmission | ... │
├─────────────────────────────────────────────────────────────────┤
│                    Shifter Platform                             │
│         (CMS, Provisioner, Auth, Notifications)                 │
└─────────────────────────────────────────────────────────────────┘
```

## Phase Summary

| Phase | Description | Status | Effort |
|-------|-------------|--------|--------|
| 1-4 | Core Models, Services, Forms, Event/Challenge UI | Complete | - |
| 5 | [Participant Management](./phase-5-participant-management.md) | Pending | 21h |
| 6 | [Participant Portal](./phase-6-participant-portal.md) | Pending | 38h |
| 7 | [Range Integration & Notifications](./phase-7-range-integration-notifications.md) | Pending | 46h |
| **Total Remaining** | | | **105h** |

## What's Already Built

### Models (`ctf/models.py`)
- `CTFEvent` - Competition events with scheduling, team mode
- `CTFChallenge` - Challenges with categories, points, hints
- `CTFTeam` - Team groupings for team-based events
- `CTFParticipant` - Individual competitors with invite/registration flow
- `CTFSubmission` - Flag submission attempts and scoring
- `CTFNotification` - Email notification records
- `CTFScheduledTask` - Automated task scheduling

### Services (`ctf/services/`)
- `event.py` - Event lifecycle (create, schedule, activate, complete, cancel)
- `challenge.py` - Challenge CRUD, flag hashing/verification
- `participant.py` - Invite, register, import, disqualify
- `scoring.py` - Score calculation, leaderboards
- `submission.py` - Flag submission, hint usage
- `notification.py` - Email sending (stubs)
- `range.py` - Range integration (minimal)

### Forms (`ctf/forms.py`)
- `CTFEventForm` - Event create/edit
- `CTFChallengeForm` - Challenge create/edit with flag hashing
- `CTFParticipantForm` - Single participant add
- `CTFParticipantImportForm` - CSV bulk import
- `CTFNotificationForm` - Notification compose
- `EventStatusForm` - Status transitions

### Views (`ctf/views.py`)
- Admin dashboard, event list, create, edit, detail - **Working**
- Challenge list, create, edit, detail - **Working**
- Participant views - **Stubbed**
- Participant portal views - **Stubbed**
- API endpoints - **Stubbed**

### Templates (`templates/ctf/`)
- Admin templates - Partially complete
- Participant templates - Placeholder content

## Key Design Decisions

### Authentication
- Organizers: Shifter platform users with `is_ctf_organizer` flag
- Participants: Invited via email, register through Cognito
- Decorators: `@ctf_organizer_required`, `@ctf_participant_required`

### Flag Security
- Flags stored as bcrypt hashes (with SHA256 fallback)
- Submitted flags compared using constant-time comparison
- All submission attempts logged for audit

### Event Lifecycle
```
DRAFT → SCHEDULED → ACTIVE → COMPLETED
                 ↘         ↗
                   CANCELLED
```

### Participant Lifecycle
```
INVITED → REGISTERED → ACTIVE → COMPLETED
                    ↘       ↗
                   DISQUALIFIED
```

### Scoring
- Points per challenge with difficulty weighting
- Optional hint penalty (percentage reduction)
- Tie-breaker: earlier last solve time wins
- Team mode: aggregated member scores

## Dependencies

- **Django 5.x** - Web framework
- **PostgreSQL** - Database
- **Celery** - Task scheduling
- **AWS SES** - Email sending
- **AWS Cognito** - Participant authentication
- **bcrypt** - Flag hashing
- **Shifter CMS** - Range provisioning

## File Structure

```
shifter/shifter_platform/ctf/
├── __init__.py
├── admin.py
├── apps.py
├── context_processors.py
├── enums.py              # Status enums
├── exceptions.py         # Custom exceptions
├── forms.py              # Django forms
├── models.py             # Database models
├── urls.py               # URL routing
├── views.py              # View functions
├── services/
│   ├── __init__.py
│   ├── challenge.py
│   ├── event.py
│   ├── notification.py
│   ├── participant.py
│   ├── range.py
│   ├── scoring.py
│   └── submission.py
├── tests/
│   ├── conftest.py       # pytest fixtures
│   ├── factories.py      # Model factories
│   ├── test_auth.py
│   ├── test_challenges.py
│   ├── test_events.py
│   └── test_models.py
└── migrations/
    └── 0001_initial.py
```

## Next Steps

1. **Phase 5**: Implement participant management views and APIs
2. **Phase 6**: Build out participant portal for competition
3. **Phase 7**: Integrate range provisioning and email notifications

## Testing Strategy

- Use pytest with Django test client
- Factory Boy for model fixtures
- Mock external services (SES, Provisioner)
- Integration tests for full workflows
- See individual phase docs for test requirements
