---
id: UX-013
title: "Screen reader support"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:59.031840Z
updated_at: 2026-05-09T04:37:59.031840Z
---

# UX-013: Screen reader support

## Statement

Every page shall use semantic HTML landmarks and a logical heading hierarchy. Every interactive element shall have a programmatic accessible name. ARIA shall be used only where native semantics are insufficient. Asynchronous state changes that affect the user, including range provisioning status, scoring updates, terminal output, and form submission results, shall be announced through ARIA live regions with appropriate politeness levels.

## Rationale

Screen readers cannot meaningfully convey UI built only with divs and JavaScript event handlers. Async updates are particularly bad: the current platform has substantial async behavior (range provisioning, scoring, terminal) that today produces nothing in a screen reader.
