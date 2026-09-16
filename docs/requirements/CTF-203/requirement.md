---
id: CTF-203
title: "Hint Penalty Application"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.964555Z
updated_at: 2026-03-19T04:31:29.467438Z
---

# CTF-203: Hint Penalty Application

## Statement

The system should deduct the configured hint penalty from a participant's score when they use a hint on a challenge. Penalties shall be subtracted from the points awarded for that challenge's solve, not from the participant's total score. If a participant uses a hint but never solves the challenge, no penalty shall be applied. The net score for a challenge solve shall never go below zero.

## Rationale

Hint penalties create a strategic trade-off: use a hint to get unstuck but earn fewer points, or persist without help for full credit. CTFd implements hint costs that reduce challenge points. This mechanic keeps hints from being free shortcuts while still providing a lifeline for stuck participants.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py::submit_flag` (submit_flag() - Applies hint penalty on correct submission only)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py::test_challenge_calculate_points_with_penalty` (Tests for hint penalty calculation (with and without penalty))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (TestSubmitFlagHintPenalty, 0-floor + unsolved-hint score-neutrality (issue #519))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#519` (CTF-203: floor net solve points at 0 (was 1))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/challenge.py::CTFChallenge.calculate_points_with_penalty` (calculate_points_with_penalty(), hint penalty calculation per challenge (0-floor since issue #519))
