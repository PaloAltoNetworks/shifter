---
id: CTF-304
title: "Hint Cost/Purchase"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.254561Z
updated_at: 2026-03-29T18:55:02.945357Z
---

# CTF-304: Hint Cost/Purchase

## Statement

The system could require participants to explicitly confirm spending points before a hint is revealed, presenting the cost and requiring acknowledgment. If a participant's current score minus the hint cost would result in a negative net score for the associated challenge, the system should warn but still allow the purchase.

## Rationale

The purchase confirmation step prevents accidental hint consumption, which is irreversible. Without a confirmation gate, misclicks or interface confusion could cost participants points they did not intend to spend. (CTFd shows cost before unlock and requires confirmation.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (Challenge detail template - has confirm() dialog for hint reveal with cost display)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (Submission service - hint_used tracking but no negative-score warning)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_hint.py` (TestHintPurchaseContext - view-level tests for hint cost/purchase context variables)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#567` (CTF-304: Hint Cost/Purchase)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant_challenges.py` (Challenge detail view - computes hint cost context variables for purchase confirmation)
