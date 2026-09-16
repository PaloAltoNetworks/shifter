---
id: CTF-606
title: "Hidden Users"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.945170Z
updated_at: 2026-03-26T06:38:35.858Z
---

# CTF-606: Hidden Users

## Statement

The system could support hiding specific participants from the public scoreboard while allowing them to continue participating normally. Hidden participants shall still be able to view their own scores and submit flags. Their scores shall not affect other participants' rankings. Organizers shall see hidden participants in the admin view.

## Rationale

Hidden users enable organizers or test accounts to participate without distorting the competitive scoreboard. For Shifter, organizers may want to test challenges during a live event without appearing on the leaderboard and confusing real participants. (CTFd supports hidden users.)

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#655` (CTF-606: Hidden Users)
