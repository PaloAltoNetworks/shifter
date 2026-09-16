---
id: CTF-702
title: "Event Timing"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:23.118958Z
updated_at: 2026-04-05T22:43:58.795633Z
---

# CTF-702: Event Timing

## Statement

The system shall support configuring event start and end times as UTC timestamps. The system shall display times in the participant's local timezone. Events shall not accept flag submissions before start time or after end time, regardless of state. The system shall display a countdown timer to participants showing time remaining until event start or end.

## Rationale

Precise timing is fundamental to competitive fairness, all participants must have the same competition window. CTFd enforces start/end times. For Shifter events spanning multiple timezones (PANW is global), UTC storage with local display prevents timezone confusion that could give some participants more or less time.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (Flag submission service, time-boundary enforcement)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/event.html` (Participant event template, countdown timer and local timezone display)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/static/js/ctf-event-timing.js` (Event timing JS, local timezone conversion and countdown timer)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFEvent model, event_start, event_end, event_timezone fields)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (Submission tests, time-boundary enforcement (TestTimeBoundaryEnforcement))
- TESTS → TEST `shifter/shifter_platform/static/js/ctf-event-timing.test.js` (Event timing JS tests, formatDuration, formatLocalTime)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#583` (CTF-702: Event Timing)
