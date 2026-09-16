---
id: CTF-506
title: "Team Password Joining"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.720536Z
updated_at: 2026-03-26T06:38:26.495565Z
---

# CTF-506: Team Password Joining

## Statement

The system could support an alternative team join mechanism where teams set a shared password and participants join by providing the team name and password. This shall be an alternative to invite codes, not a replacement. Teams shall be able to use either or both mechanisms.

## Rationale

Password-based joining is simpler than invite codes for casual events where security is less important. For informal Shifter training sessions, a simple password is lower friction than generating and distributing invite codes. (CTFd supports team passwords.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py (CTFTeam model)` (CTFTeam model - has invite_code but no password field)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py (team_join view)` (team_join view - uses invite_code only, no password mechanism)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#649` (CTF-506: Team Password Joining)
