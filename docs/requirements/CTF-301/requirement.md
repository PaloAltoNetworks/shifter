---
id: CTF-301
title: "Hint Creation"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.133832Z
updated_at: 2026-03-30T04:46:19.505995Z
---

# CTF-301: Hint Creation

## Statement

The system should support creating one or more hints per challenge. Each hint shall have: content text (supporting Markdown), a display order for progressive revelation, and an optional point cost. Hints shall be ordered so participants see less-specific hints before more-specific ones.

## Rationale

Hints are the primary scaffolding mechanism for participants who are stuck. Progressive hints (general first, specific later) let participants choose how much help they need, maintaining the challenge while preventing complete frustration. (CTFd models hints as ordered, per-challenge entities with costs.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFHint model - text, penalty, order fields with FK to challenge)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/hint.py` (Hint service - add_hint, update_hint, remove_hint, get_hints CRUD)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_hint.py` (TestHintCRUD - add, remove, ordering tests for hint creation)
