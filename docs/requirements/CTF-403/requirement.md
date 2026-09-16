---
id: CTF-403
title: "Scoreboard Freeze"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.358352Z
updated_at: 2026-04-02T04:27:56.326088Z
---

# CTF-403: Scoreboard Freeze

## Statement

The system could support freezing the public scoreboard at a configurable time before event end. After freeze, participants continue to see their own updated score but the public scoreboard displays frozen standings. Organizers shall see the real-time scoreboard regardless of freeze state. The freeze shall be lifted when the event ends or when an organizer manually unfreezes.

## Rationale

Scoreboard freeze is a standard CTF practice that maintains suspense in the final hours, participants know their own progress but cannot see if competitors are catching up. Without freeze, the final stretch loses its excitement as outcomes become obvious before the event ends. (CTFd supports scoreboard freeze.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF Models - CTFEvent lacks scoreboard_freeze_time field)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Scoring service - no freeze logic in get_scoreboard)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py` (Event service - scoreboard_freeze_at in mutable fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (CTFEventForm - scoreboard_freeze_at field)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0019_add_scoreboard_freeze.py` (Migration adding scoreboard_freeze_at to CTFEvent)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring.py` (Scoring tests - TestScoreboardFreeze and TestIsScoreboardFrozen)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#574` (CTF-403: Scoreboard Freeze)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (Views - freeze_at passed to scoring for participants, organizers see real-time)
