---
id: CTF-604
title: "Participant Roles"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:22.869388Z
updated_at: 2026-03-26T06:10:51.252561Z
---

# CTF-604: Participant Roles

## Statement

The system shall support distinct event-scoped participation roles: organizer (full event management), participant (can view challenges and submit flags), and observer (can view scoreboard but cannot submit flags). Role assignment shall be per-event, the same user may be an organizer in one event and a participant in another. Only organizers shall be able to change event roles. Event-scoped roles compose with the platform's existing role/permission system (Django Groups) and do not replace it.

## Rationale

Role separation ensures participants cannot accidentally or intentionally modify event configuration while organizers need full control. CTFd supports admin/user distinction. Shifter adds the observer role for stakeholders (managers, customers) who want to watch events without competing.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/auth.py` (CTF role group constants and helper functions (organizer, participant))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/bridges.py` (UserRole dataclass and get_user_role() role detection)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py` (Per-event participant role assignment (_set/_clear_ctf_participant_profile))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFParticipant model with per-event FK (event-scoped participation))
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_auth.py` (Dual-role and per-event role assignment tests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (UserType enum (ctf_organizer, ctf_participant -- no observer))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums_registration.py` (Event-scoped PLAYER and OBSERVER participation roles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#653` (CTF-604: Participant Roles)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/_access.py` (Role-gating decorators (ctf_organizer_required, ctf_participant_required, ctf_role_required))
