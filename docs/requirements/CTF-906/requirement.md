---
id: CTF-906
title: "Per-Event Instance Visibility"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.645727Z
updated_at: 2026-03-19T04:02:50.856530Z
---

# CTF-906: Per-Event Instance Visibility

## Statement

The system should ensure that participants can only see and access range instances associated with their CTF event. A participant registered for Event A shall not see instances from Event B, even if both events use the same scenario template. The Mission Control dashboard shall filter CTF instances from the normal range listing unless the user is also a Mission Control user.

## Rationale

Instance visibility isolation prevents information leakage between concurrent events and between CTF and Mission Control usage. Without isolation, participants could discover other events' ranges or confuse their CTF instances with their regular Mission Control ranges, creating security and usability issues.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (CTF submission service - cross-event flag submission prevention)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py` (CTF participant service - user-event binding, active_ctf_event scoping)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/auth.py` (Auth utilities - is_ctf_participant_only() role detection)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services.py` (CMS services - get_active_range() filters by user_id ownership)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/mission_control/dashboard.html` (MC dashboard template - hides Launch Range for CTF-only users, viewOnly mode)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/context_processors.py` (MC context processor - CTF participant instance filtering (Kali-only))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/context_processors.py` (CTF context processor - is_ctf_participant_only flag for templates)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range/provision.py` (CTF per-participant range provisioning and isolation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/_access.py` (CTF views - per-event access control, challenge/event isolation)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_mid_event_operations.py` (Per-event range visibility tests - same-scenario active events cannot see each other's ranges)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
