---
id: CTF-117
title: "Challenge Solutions"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T20:38:43.027671Z
updated_at: 2026-03-28T21:20:43.365661Z
---

# CTF-117: Challenge Solutions

## Statement

The system should support attaching an official solution or writeup to each challenge. Solutions shall be visible only to organizers during an active event. Organizers shall be able to reveal solutions to participants after the event ends. Solutions shall support rich text content including code blocks and images.

## Rationale

Solutions serve as training material after events, participants learn how challenges were meant to be solved, which is critical for Shifter's training-focused use case. Without solutions, the educational value of completed events is lost. Organizers need a way to document the intended solve path per challenge and reveal it after the event ends. (CTFd supports a similar Solution tab per challenge.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge.solution TextField)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (solution in _CHALLENGE_MUTABLE_FIELDS for create/update)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (Conditional solution display (visible after event ends/archived))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenges.py` (TestChallengeSolutions: create, default, mutable fields, update tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#551` (CTF-117: Challenge Solutions)
