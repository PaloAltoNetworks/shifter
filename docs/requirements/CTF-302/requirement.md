---
id: CTF-302
title: "Hint Point Penalties"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.183715Z
updated_at: 2026-03-30T04:50:19.769553Z
---

# CTF-302: Hint Point Penalties

## Statement

The system should support configuring a point penalty value for each hint. The penalty shall be expressed as a positive integer representing points deducted from the challenge score upon hint consumption. Different hints for the same challenge may have different penalty values (for example first hint costs 10 points, second costs 25). A penalty of zero shall be permitted for free hints.

## Rationale

Variable hint costs let organizers calibrate the trade-off between help and score impact. A small first hint might be cheap to nudge participants in the right direction, while a near-giveaway final hint costs most of the challenge points. Scoring behavior upon hint consumption is defined in CTF-203. (CTFd supports per-hint cost configuration.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFHint.penalty field - per-hint percentage penalty (0-100), different per hint, zero allowed)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/hint.py` (add_hint with penalty param, get_total_hint_penalty cumulative calculation)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_hint.py` (TestHintUsage - total penalty calculation, penalty capping at 100, per-hint penalty values)
