---
id: CTF-201
title: "Standard Scoring"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.885645Z
updated_at: 2026-03-19T04:20:10.912932Z
---

# CTF-201: Standard Scoring

## Statement

When standard scoring mode is selected, the system shall support point-based scoring where each challenge has a fixed point value assigned by the organizer at creation time. A correct flag submission shall award the full point value to the participant. Points shall not change based on the number of solves.

## Rationale

Standard scoring is the simplest and most widely understood CTF scoring model. CTFd defaults to this mode. It provides predictable, transparent scoring that participants can reason about when deciding which challenges to attempt. All other scoring modes (dynamic, hints) are variations built on top of standard scoring.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge model - fixed points field and calculate_points_with_penalty)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (submit_flag - awards full point value on correct submission)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Scoring service - aggregates points_awarded, no dynamic recalculation)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (Tests for fixed points and calculate_points_with_penalty)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/conftest.py` (Test fixtures - correct submission awards challenge.points)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_strategy.py` (StandardScoringStrategy, fixed challenge value, less hint penalty, independent of solve count)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring_mode.py` (Standard-scoring tests, full fixed value on solve, solve-count independence, hint-penalty modifier)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#520` (CTF-201: Introduce explicit CTF event scoring mode configuration (standard mode))
