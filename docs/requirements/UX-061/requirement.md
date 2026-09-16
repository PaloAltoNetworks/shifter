---
id: UX-061
title: "Right-to-left layout support"
status: DRAFT
type: NON_FUNCTIONAL
priority: COULD
created_at: 2026-05-09T04:39:28.292124Z
updated_at: 2026-05-09T04:39:28.292124Z
---

# UX-061: Right-to-left layout support

## Statement

The design system shall support right-to-left layouts. Components shall use logical CSS properties (margin-inline-start, padding-inline-end, etc.) rather than physical ones, and the design system shall be tested in both LTR and RTL configurations.

## Rationale

RTL support is cheap to bake in from the start of a design system and prohibitively expensive to retrofit. Using logical properties is also a generally cleaner pattern that improves the design system regardless of whether RTL is ever activated.
