---
id: CTF-406
title: "Tie-Breaking Rules"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:22.466284Z
updated_at: 2026-03-26T06:37:49.598511Z
---

# CTF-406: Tie-Breaking Rules

## Statement

The system shall implement deterministic tie-breaking rules when two or more participants have the same total score. The primary tie-breaker shall be the timestamp of the participant's most recent solve, the participant who reached that score first shall rank higher. The tie-breaking rule shall be documented and visible to participants.

## Rationale

Ties are common in CTF events, especially when multiple participants solve the same set of challenges. Without deterministic tie-breaking, rankings are arbitrary and disputes arise. Using earliest-solve-time as the tie-breaker is the community standard and incentivizes speed alongside accuracy. (CTFd uses the same earliest-solve-time approach.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Scoring service: get_scoreboard and get_team_scoreboard with timestamp tie-breaking)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/templates/ctf/help.html` (CTF Help page documenting tie-breaking rule visible to participants)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/scoreboard.html` (Participant scoreboard template showing rank, score, and last solve time)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/scoreboard.html` (Admin scoreboard template showing rank, score, and last solve time)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (CTF views dispatching individual/team scoreboards consistently)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_read.py::get_scoreboard` (Scoreboard read path - deterministic score and earliest-last-solve tie ordering)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring.py` (Scoring tests - deterministic tie-breaking by score and earliest last-solve order)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
- DOCUMENTS → GITHUB_ISSUE `521` (Issue #521 - scoreboard repair preserves CTF-406 tie-breaking (no re-rank in presentation))
