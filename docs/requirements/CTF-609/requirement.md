---
id: CTF-609
title: "Participant Disqualification"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.048012Z
updated_at: 2026-03-26T06:38:38.096787Z
---

# CTF-609: Participant Disqualification

## Statement

The system should support disqualifying participants from an event. A disqualified participant shall be removed from scoreboard rankings and their solves shall not count toward statistics. Unlike banning, disqualified participants may still view event content but cannot submit flags. Disqualification shall record a reason. Organizers shall be able to reverse disqualification.

## Rationale

Disqualification is a softer action than banning, it removes competitive standing without locking out the participant entirely. This is appropriate when rule violations are discovered but the participant should still be able to observe. For enterprise events, disqualification handles situations diplomatically. (CTFd supports a similar disqualification mechanism.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py (disqualify_participant)` (disqualify_participant() - sets status to DISQUALIFIED, clears CTF participant profile)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py (get_scoreboard)` (Scoreboard excludes DISQUALIFIED participants (filters by ACTIVE/REGISTERED/COMPLETED only))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums_registration.py (ParticipantStatus.DISQUALIFIED)` (DISQUALIFIED enum value)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#657` (CTF-609: Participant Disqualification)
