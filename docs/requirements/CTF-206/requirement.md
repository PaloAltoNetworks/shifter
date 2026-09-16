---
id: CTF-206
title: "Score Calculation"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:22.081960Z
updated_at: 2026-03-20T05:23:24.632632Z
---

# CTF-206: Score Calculation

## Statement

The system shall calculate each participant's total score as the sum of: points earned from challenge solves (after any dynamic scoring adjustments), minus hint penalties consumed, plus any organizer-granted awards. Score calculation shall be deterministic, given the same inputs, it shall always produce the same result. The system shall recalculate scores when scoring-relevant events occur (solve, hint use, award grant, dynamic score adjustment).

## Rationale

Accurate score calculation is the foundation of competitive integrity. Every scoreboard, ranking, and tie-breaking decision depends on correct scores. CTFd computes scores from the combination of solves, penalties, and awards. Any error in score calculation undermines participant trust and event legitimacy.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Scoring service - calculate_score(), get_scoreboard(), get_team_scoreboard())
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (Submission service - submit_flag() with hint penalty calculation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/award.py` (Award service (grant, revoke, list))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/admin.py` (CTFAward admin and score annotation updates)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_awards.py` (Award and score+award integration tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#508` (CTF-206: Score Calculation)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (TestSubmitFlagHintPenalty, calculate_score reflects hint-penalty-baked points_awarded (issue #519))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#519` (CTF-206: aggregate score remains correct with hint-penalised solves)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/challenge.py` (CTFChallenge.calculate_points_with_penalty(), net solve points (split from models.py in PR #856))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/submission.py` (CTFSubmission.points_awarded, stored net solve points; CTFAward.points, organizer awards)
