---
id: CTF-401
title: "Individual Scoreboard"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:22.289425Z
updated_at: 2026-03-26T06:37:37.525855Z
---

# CTF-401: Individual Scoreboard

## Statement

The system shall display an individual participant scoreboard ranked by total score in descending order. The scoreboard shall show: rank, participant display name, total score, number of challenges solved, and time of last solve. The scoreboard shall update in near-real-time (within 30 seconds of a scoring event). Participants shall be able to click a row to see that participant's solve history.

## Rationale

The individual scoreboard is the central competitive interface for non-team events. Participants check the scoreboard constantly to assess their position and decide strategy. Delayed or inaccurate scoreboards undermine the competitive experience. (CTFd provides a real-time scoreboard as its primary view.)

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/services/scoring.py` (Scoring service - get_scoreboard() ranked by descending score with solve_count, last_solve, rank)
- IMPLEMENTS → CODE_FILE `ctf/views.py` (Scoreboard view (participant) and api_scoreboard JSON endpoint)
- IMPLEMENTS → CODE_FILE `templates/ctf/participant/scoreboard.html` (Scoreboard template - renders rank, name, score, solves, last_solve with 15-second auto-refresh polling)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_read.py::get_scoreboard` (Individual scoreboard read path - rank, participant display, score, solve count, last solve)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring.py` (Scoring tests - individual scoreboard ranking, score recomputation/materialization, solve count and last solve)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (Participant scoreboard view: participant_id context wiring + own-row solve-history drill-down (PR #1304))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoreboard_views.py` (Scoreboard view tests: participant_id highlight wiring + own-row drill-down (PR #1304))
- IMPLEMENTS → GITHUB_ISSUE `521` (Issue #521 - Repair participant scoreboard wiring and add solve-history drill-down)
