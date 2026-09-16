---
id: CTF-111
title: "Challenge Release Scheduling"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.776711Z
updated_at: 2026-03-26T06:36:29.757418Z
---

# CTF-111: Challenge Release Scheduling

## Statement

The system should support scheduling challenges to automatically transition from hidden to visible at a specified date and time. Organizers shall configure release times per challenge. The system shall process scheduled releases within one minute of the configured time.

## Rationale

Timed challenge releases maintain engagement throughout multi-hour or multi-day events by introducing new content at intervals rather than dumping everything at start. For Shifter events that span a full workday, staggered releases keep participants engaged across sessions. (CTFd supports scheduled releases.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge.release_time field and is_released property (lines 468, 517-522))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (get_available_challenges release_time filter (line 282-284))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (submit_flag is_released gate (lines 90-97))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` (RELEASE_CHALLENGE handler and TASK_HANDLERS registration)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (`ScheduledTaskType.RELEASE_CHALLENGE` enum value)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenge_release.py` (Challenge release scheduling tests (15 tests))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#545` (CTF-111: Challenge Release Scheduling)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
