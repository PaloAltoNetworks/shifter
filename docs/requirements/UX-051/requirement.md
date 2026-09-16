---
id: UX-051
title: "Visual regression testing"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:39:10.382656Z
updated_at: 2026-05-09T04:39:10.382656Z
---

# UX-051: Visual regression testing

## Statement

Component-level visual regression tests shall run in continuous integration to catch unintended visual drift. Snapshot diffs shall require explicit reviewer acknowledgement to land.

## Rationale

CSS changes have spooky-action-at-a-distance side effects: a token tweak in the design system can ripple to dozens of components. Visual regression testing surfaces those changes at the moment they happen, not when a user notices weeks later.
