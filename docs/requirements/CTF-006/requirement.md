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

The CTF layer shall manage event-scoped participant lifecycle from onboarding through event completion, providing organizers with controls over who can participate and in what capacity. Participants resolve Management-owned principals; isolated email-free human accounts retain their restricted login/recovery flow, while independently authorized service principals may participate for QA without dummy human users. CTF owns event-scoped participation state, roles, team membership and lifecycle predicates. Temporary credentials cannot escape their event or acquire platform/credential administration authority.

## Rationale

Participant management is the gatekeeping layer for CTF events. Isolated-account login and established password recovery are preserved. The old participant magic-link flow was retired by migration 0033 (#1206), not restored by #2316. Event-scoped lifecycle remains distinct from platform administration, and a service's participant authority does not inherit its creator's authority.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/principal_participants.py` (Explicit event-scoped admission and participant-safe read through neutral credentials)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/principal_participation.py` (Explicit service participation and live event/credential predicates)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/unified_authorization.py` (Live exact event action and credential-ceiling check for service participation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/credential_scope.py` (Temporary credential context restricted to one event)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_service_participation.py`
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_unified_authorization.py` (Service and temporary event-authority boundaries)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums_registration.py` (ParticipantStatus enum - registered/active/completed/disqualified/banned lifecycle states)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_people.py` (Organizer participant CRUD and role-based access control)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant/lifecycle.py` (Participant lifecycle service - organizer add via immediate provisioning, resend login info, delete)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant/accounts.py` (Isolated participant account provisioning - provision_participant_seat seam shared by add/import/generated-seat creation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant/credentials.py` (Volatile password issuance and non-secret ledger login notices; legacy dispatch retired by ADR-065)
- IMPLEMENTS → GITHUB_ISSUE `535` (Clarify the participant lifecycle model around invite vs auto-registration (CTF-006))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/team.py` (CTFParticipant model - lifecycle fields (status, registered_at, login_info_sent_at), capacity/uniqueness constraints, team membership)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_views.py` (Participant view tests - admin list/status-filter/import/detail, API CRUD)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_accounts.py` (Isolated participant account tests - immediate-provisioning invariant, account confinement, capacity locks)
