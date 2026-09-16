---
id: CTF-006
title: "Participant Management"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.088655Z
updated_at: 2026-03-26T06:33:32.118062Z
---

# CTF-006: Participant Management

## Statement

The CTF layer shall manage event-scoped participant lifecycle from onboarding through event completion, providing organizers with controls over who can participate and in what capacity. CTF participants are platform users managed by the Management layer; CTF adds event-scoped participation state, roles, and team membership.

## Rationale

Participant management is the gatekeeping layer for CTF events. Shifter consultants need frictionless onboarding via the platform's authentication (OIDC/SSO or magic links via PLAT-101) since they cannot install software on work laptops. Role separation ensures organizers can manage events without granting admin access. Event-scoped participation state is the CTF-specific addition on top of platform user management.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums_registration.py` (ParticipantStatus enum - registered/active/completed/disqualified/banned lifecycle states)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_people.py` (CTF views - organizer participant CRUD, magic link registration, role-based access control)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant/lifecycle.py` (Participant lifecycle service - organizer add via immediate provisioning, resend login info, delete)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant/accounts.py` (Isolated participant account provisioning - provision_participant_seat seam shared by add/import/generated-seat creation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification/_participant.py` (Participant notifications - login-information delivery, credentials, reminders, announcements)
- IMPLEMENTS → GITHUB_ISSUE `535` (Clarify the participant lifecycle model around invite vs auto-registration (CTF-006))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/team.py` (CTFParticipant model - lifecycle fields (status, registered_at, login_info_sent_at), capacity/uniqueness constraints, team membership)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_views.py` (Participant view tests - admin list/status-filter/import/detail, API CRUD)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_accounts.py` (Isolated participant account tests - immediate-provisioning invariant, account confinement, capacity locks)
