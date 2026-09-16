---
id: CTF-303
title: "Hint Usage Tracking"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.218465Z
updated_at: 2026-03-30T04:53:19.251749Z
---

# CTF-303: Hint Usage Tracking

## Statement

The system should track which participants have consumed which hints, recording the participant, hint, and timestamp of consumption. A consumed hint shall remain visible to the participant for the remainder of the event. Hint consumption shall be irreversible. Organizers shall be able to view hint usage statistics per challenge and per participant.

## Rationale

Hint tracking is necessary for accurate score calculation (penalty application) and for organizer analytics. Knowing which hints were consumed reveals where participants struggle, informing future challenge design. Without tracking, penalties cannot be applied and usage analytics are impossible. (CTFd tracks hint unlocks per user.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFHintUsage model - tracks participant, hint, and unlocked_at timestamp)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/hint.py` (use_hint (irreversible consumption), get_unlocked_hints (persistent visibility), get_total_hint_penalty)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_hint.py` (TestHintUsage - unlock tracking, idempotent re-unlock, unlocked hints retrieval)
