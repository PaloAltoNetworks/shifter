---
id: UX-011
title: "Full keyboard operability"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:50.375312Z
updated_at: 2026-05-09T04:37:50.375312Z
---

# UX-011: Full keyboard operability

## Statement

Every interactive control on every surface shall be reachable and operable using a keyboard alone, with no reliance on a pointer device. This includes modals (with focus trap and restoration on close), menus, dropdowns, the in-browser terminal, and any custom widget. Focus order shall match visual reading order. Keyboard shortcuts, where used, shall not conflict with assistive technology shortcuts.

## Rationale

Keyboard operability is foundational for screen reader users, motor impairment users, and power users in general. The current platform has not been audited; the in-browser terminal in particular needs explicit attention because xterm.js and surrounding chrome interact in ways that often trap or lose focus.
