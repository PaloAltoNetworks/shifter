---
id: CTF-005
title: "Team Management"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.045742Z
updated_at: 2026-03-26T06:35:58.597540Z
---

# CTF-005: Team Management

## Statement

The system should support team-based CTF participation where participants collaborate within named groups, share a team score, and are managed by a designated team captain.

## Rationale

Many CTF events are team-based, where collaboration is part of the learning exercise. For Shifter, team mode is important for scenarios where consultants work together on demo environments or when running training exercises for customer teams. (CTFd supports both individual and team modes.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFTeam model with name, captain, event FK, and unique constraint)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Team scoreboard with get_team_scoreboard() aggregation)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (TestCTFTeamModel - team creation, unique name constraint tests)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/conftest.py` (CTFTeam fixtures (ctf_team, ctf_event_team) for team tests)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_events.py` (Team mode event form validation tests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (participant_team and team_join views for team membership UI)
