---
id: CTF-204
title: "Awards/Bonus Points"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.000543Z
updated_at: 2026-03-26T06:37:13.297578Z
---

# CTF-204: Awards/Bonus Points

## Statement

The system could support organizer-granted bonus point awards to participants outside of challenge solves. Awards shall have a name, description, point value (positive or negative), and recipient. Awards shall appear in the score breakdown and contribute to the participant's total score.

## Rationale

Awards enable organizers to recognize exceptional behavior (creative solutions, helping others, finding unintended bugs) or penalize rule violations without disqualifying. They provide flexibility for situations the scoring system cannot anticipate, such as ad-hoc bonuses or deductions during live events. (CTFd supports awards as a similar scoring mechanism.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF models - no CTFAward model exists)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#642` (CTF-204: Awards/Bonus Points)
