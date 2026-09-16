---
id: CTF-114
title: "Submission Rate Limiting"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T07:23:00.239259Z
updated_at: 2026-03-26T15:06:34.600472Z
---

# CTF-114: Submission Rate Limiting

## Statement

The system should enforce a configurable rate limit on flag submissions per participant per challenge (for example no more than 1 submission per 10 seconds). Rate-limited submissions shall be rejected with a clear message indicating when the participant may retry. Rate limit parameters shall be configurable per event.

## Rationale

Rate limiting prevents automated brute-force flag guessing, which undermines competition integrity. This is separate from attempt count limits (CTF-112), rate limiting controls submission frequency while attempt limits control total tries. (CTFd implements submission throttling as a core anti-abuse mechanism.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/exceptions.py` (CTFRateLimitError exception class (exists but not used for time-based rate limiting))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (submit_flag() -- no time-based rate limiting implemented)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#547` (CTF-114: Submission Rate Limiting)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_submit_flag_rate_limit_api.py` (API integration test: submit_flag 429 cooldown envelope with Retry-After)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/play.py` (api_submit_flag 429 response with retry_after_seconds and Retry-After header)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (TestSubmissionRateLimit, cooldown enforcement, per-challenge scope, retry details)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (submitFlag() branches on HTTP 429 for cooldown messaging)
