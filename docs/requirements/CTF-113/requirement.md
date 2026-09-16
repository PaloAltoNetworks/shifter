---
id: CTF-113
title: "Challenge Tags"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:21.848842Z
updated_at: 2026-03-27T03:26:55.522847Z
---

# CTF-113: Challenge Tags

## Statement

The system could support tagging challenges with freeform metadata labels (for example `XDR`, `Cortex`, `Linux`, `Windows`, `network`). Tags shall be searchable and filterable in the challenge listing. A challenge may have multiple tags. Tags shall be reusable across challenges within an event.

## Rationale

Tags provide a secondary organizational axis orthogonal to categories. A forensics challenge could be tagged with both "Windows" and "XDR" to help participants find challenges relevant to specific products or platforms. For Shifter, tags enable filtering by PANW product (XDR, XSIAM, Cortex) which categories alone cannot capture. (CTFd supports a similar tagging feature.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallengeTag model and tags M2M field on CTFChallenge)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (Tag resolution in create_challenge() and update_challenge())
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenges.py` (TestChallengeTags: create, update, reuse, uniqueness, clear tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#550` (CTF-113: Challenge Tags)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant_challenges.py` (Tag filtering in participant_challenges() and tags in API responses)
