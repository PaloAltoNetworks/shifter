---
id: CTF-003
title: "Hint System"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:20.976341Z
updated_at: 2026-03-29T18:11:56.532816Z
---

# CTF-003: Hint System

## Statement

The system should allow organizers to attach progressive, ordered hints to challenges that participants can unlock to receive guidance, with configurable point penalties that create a meaningful trade-off between assistance and score.

## Rationale

Hints prevent participants from getting completely stuck while maintaining competitive balance through point penalties. Without them, less experienced participants disengage from difficult challenges, reducing training value. A hint system is a key engagement mechanism for keeping all skill levels active. (CTFd provides a similar hint capability.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFHint and CTFHintUsage models, calculate_points_with_penalty(total_hint_penalty))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/hint.py` (Progressive hint service: add/remove/use_hint, sequential ordering, cumulative penalty)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (Progressive hint UI: sequential unlock, penalty display, locked hints)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_hint.py` (Progressive hint tests: CRUD, sequential order, penalty cap, idempotent unlock, event state)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#566` (CTF-003: Hint System)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/hints.py` (Hint management APIs (organizer), progressive hint unlock API (participant))
