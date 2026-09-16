---
id: CTF-002
title: "Scoring System"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:20.937653Z
updated_at: 2026-03-26T06:35:56.204639Z
---

# CTF-002: Scoring System

## Statement

The system shall accurately calculate and track participant scores throughout a CTF event, supporting at least one configurable scoring mode, applying hint penalties correctly, and producing deterministic results suitable for competitive ranking.

## Rationale

Accurate, real-time score computation is essential for competitive integrity and participant engagement. Scoring is what transforms challenge-solving into a competition, and organizers need configurable scoring models (static, dynamic) to match different event goals. (CTFd provides similar scoring model support.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (CTF scoring service - score calculation, scoreboards, rankings)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (CTF submission service - flag submission, hint usage, point calculation)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (Model tests - score calculation, hint penalty, points_awarded, total_score property)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_participant_views.py` (Participant view tests - scoreboard and submission views)
- TESTS → TEST `ctf/tests/test_scoring.py` (Scoring service test coverage)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (TestSubmitFlagHintPenalty, hint penalty correctness, 0-floor, unsolved-hint score-neutrality)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#519` (CTF-002: Persist CTF hint usage and fix hint penalty scoring)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/challenge.py` (CTFChallenge, points, hint penalty calculator, release/visibility validation (split from models.py in PR #856))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/submission.py` (CTFSubmission.points_awarded, stored net points (penalty already applied))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/team.py` (CTFParticipant.total_score, aggregated score property)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (CTF views - scoreboard endpoints (participant scoreboard, admin scoreboard, api_scoreboard, api_submit_flag))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_strategy.py` (Scoring-mode strategy dispatch, calculate_solve_points / get_scoring_strategy (configurable scoring mode))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/event.py` (CTFEvent.scoring_mode, organizer-configurable scoring mode field (default standard))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring_mode.py` (Scoring-mode behavior tests, default/backward-compat, strategy dispatch, submission scoring, organizer visibility, invalid-mode rejection)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#520` (CTF-002: Introduce explicit CTF event scoring mode configuration)
