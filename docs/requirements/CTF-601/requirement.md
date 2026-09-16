---
id: CTF-601
title: "Participant Registration"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:22.755543Z
updated_at: 2026-03-26T06:10:35.143869Z
---

# CTF-601: Participant Registration

## Statement

The system shall support associating platform users with CTF events via a registration flow. Registration shall collect a display name and email address, and create or link a platform user account. Registration shall be available during the registration window (between event creation and registration deadline). The system shall enforce unique email addresses per event. Registered participants shall receive a confirmation with event details. The CTF layer uses the platform's user management (Management layer) for account creation, not its own user store.

## Rationale

Self-registration is the primary onboarding path for CTF participants. CTFd supports open registration with configurable fields. For Shifter, registration must be low-friction since consultants register from various locations and devices, often at the last minute before an event.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF models - CTFParticipant with unique email constraint and CTFEvent with registration_deadline)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py` (Participant service - invite_participant, bulk_import, auto-registration logic)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py` (Notification service - send_invitations, email rendering (no registration confirmation))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (CTF forms - CTFParticipantForm collects name and email (organizer-facing))
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_auth.py` (Auth tests - TestCTFRegisterView magic link token validation)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_participant_views.py` (Participant view tests - add, import, list, detail, API participant CRUD)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_services/test_notification.py` (Notification service tests - invitation sending, credentials, rendering)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#650` (CTF-601: Participant Registration)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (CTF views - ctf_register (magic link auth, not self-registration), admin_participant_add)
