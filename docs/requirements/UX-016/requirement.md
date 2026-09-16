---
id: UX-016
title: "Reduced motion preference honored"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:38:15.972972Z
updated_at: 2026-05-09T04:38:15.972972Z
---

# UX-016: Reduced motion preference honored

## Statement

The platform shall honor the prefers-reduced-motion CSS media query. Animations, transitions, parallax effects, and any other motion shall be disabled or substantially reduced when the user has indicated a reduced-motion preference. Essential state-change motion shall be replaced with an instantaneous equivalent.

## Rationale

Vestibular disorders affect a non-trivial portion of users; for them, motion in interfaces ranges from uncomfortable to physically incapacitating. Honoring prefers-reduced-motion is an inexpensive baseline that has no cost to other users.
