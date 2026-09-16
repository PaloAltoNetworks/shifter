---
id: CTF-103
title: "Challenge Difficulty Levels"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.480501Z
updated_at: 2026-03-26T06:36:08.256970Z
---

# CTF-103: Challenge Difficulty Levels

## Statement

The system should support assigning a difficulty level to each challenge from a predefined scale (for example easy, medium, hard, expert). Difficulty levels shall be displayed alongside challenge listings to help participants gauge effort before attempting.

## Rationale

Difficulty indicators help participants allocate their limited competition time effectively. Beginners can target easy challenges to build momentum while experienced players can pursue harder ones for more points. Without difficulty levels, participants waste time on challenges beyond their skill level. (CTFd supports difficulty as a challenge attribute.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (ChallengeDifficulty enum (easy/medium/hard/expert))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge.difficulty field (line 438))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenges.html` (Difficulty badges in participant challenge listing)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (Difficulty badge in participant challenge detail)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/challenge_list.html` (Difficulty display in admin challenge listing)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/challenge_detail.html` (Difficulty badges and detail row in admin challenge detail)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/challenge_form.html` (Difficulty form field in challenge create/edit)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenge_metadata.py` (Challenge metadata tests - difficulty create/update/list/detail persistence and visibility)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
