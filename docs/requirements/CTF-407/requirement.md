---
id: CTF-407
title: "Challenge Statistics"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.503444Z
updated_at: 2026-03-26T06:37:57.637601Z
---

# CTF-407: Challenge Statistics

## Statement

The system should display per-challenge statistics including: total solve count, solve percentage (solves / total participants), number of submission attempts, and first blood holder. Statistics shall be visible to organizers at all times and optionally visible to participants (configurable per event). Statistics shall update within 30 seconds.

## Rationale

Challenge statistics help participants gauge difficulty (low solve rate = hard) and help organizers identify broken or overly easy challenges mid-event. For organizers, statistics inform decisions about releasing hints or adjusting point values during long-running events. (CTFd shows solve counts on challenge cards.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (get_challenge_statistics() - per-challenge stats (solves, solve rate, attempts, first blood))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge.first_blood property and CTFChallenge.solve_count property)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/admin.py` (CTFChallengeAdmin with solve_count_display annotation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_events.py` (admin_analytics view - renders per-challenge stats for organizers; admin_challenge_detail shows first_blood)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_stats.py::get_challenge_statistics` (Challenge statistics service - solve count, solve percentage, attempts, first blood)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring_statistics.py` (Challenge statistics tests - solve percentage, attempt count, solve count, first blood, zero-roster behavior)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
