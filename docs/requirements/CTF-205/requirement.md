---
id: CTF-205
title: "First Blood Tracking"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.037940Z
updated_at: 2026-03-26T06:37:14.290974Z
---

# CTF-205: First Blood Tracking

## Statement

The system could track and display the first participant (or team) to solve each challenge, commonly known as first blood. First blood shall be determined by the earliest correct submission timestamp. The first blood holder shall be visually highlighted on challenge detail views and optionally on the scoreboard.

## Rationale

First blood is a prestigious achievement in CTF culture that adds excitement and urgency to new challenge releases. Highlighting first solvers creates social recognition that motivates participants and adds narrative to the competition. (CTFd tracks and displays first blood per challenge.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge.first_blood property - read-only first solver tracking)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (get_challenge_statistics() returns first_blood data)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (First blood display in participant challenge detail template)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/challenge_detail.html` (First blood display in admin challenge detail template)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (test_challenge_first_blood - tests first_blood property)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_challenges.py` (View passes first_blood to challenge detail context)
