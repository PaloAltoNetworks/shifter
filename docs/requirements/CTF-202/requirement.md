---
id: CTF-202
title: "Dynamic/Decay Scoring"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:21.925502Z
updated_at: 2026-03-26T06:37:04.445127Z
---

# CTF-202: Dynamic/Decay Scoring

## Statement

When dynamic scoring mode is selected, as an alternative to standard scoring, the system could support scoring where a challenge starts at a maximum point value and decays toward a configured minimum as more participants solve it. The decay function shall be configurable (for example linear, logarithmic). When a new solve occurs, the system shall retroactively adjust all previous solvers' scores for that challenge to match the new lower value.

## Rationale

Dynamic scoring automatically balances challenge values based on difficulty, easy challenges that many solve become worth less, while hard challenges retain high value. It eliminates the need for organizers to manually guess point values and naturally rewards harder accomplishments. (CTFd supports this via its dynamic challenge plugin.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Scoring service - static scoring only, no decay functions)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#641` (CTF-202: Dynamic/Decay Scoring)
