---
id: CTF-112
title: "Challenge Attempt Limits"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.814466Z
updated_at: 2026-03-26T23:58:51.054994Z
---

# CTF-112: Challenge Attempt Limits

## Statement

The system should support configuring a maximum number of flag submission attempts per challenge per participant. The system shall support two behaviors when the limit is reached: timeout (locked out for a configurable cooldown period, then may retry) or lockout (permanently locked out of that challenge). The active behavior shall be configurable per event. Attempt limits shall be configurable per challenge with an option for unlimited attempts.

## Rationale

Attempt limits prevent brute-force flag guessing, which undermines the competitive integrity of the event. Without limits, participants can script thousands of guesses against challenges with small flag spaces, converting skill-based challenges into brute-force exercises. (CTFd supports per-challenge attempt limits.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge.max_attempts field and CTFSubmission.attempt_number field)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/exceptions.py` (CTFRateLimitError exception for attempt limit exceeded)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (submit_flag() attempt limit enforcement with lockout and timeout modes)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (AttemptLimitMode enum (lockout/timeout))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py` (attempt_limit_mode and attempt_limit_cooldown_seconds in _EVENT_MUTABLE_FIELDS)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (TestAttemptLimits: lockout, timeout, cooldown reset, unlimited, default mode tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#549` (CTF-112: Challenge Attempt Limits)
