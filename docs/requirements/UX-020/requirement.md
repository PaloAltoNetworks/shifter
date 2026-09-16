---
id: UX-020
title: "Defined state coverage for every flow"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:38:25.890501Z
updated_at: 2026-05-09T04:38:25.890501Z
---

# UX-020: Defined state coverage for every flow

## Statement

Every user flow shall have explicitly defined empty, loading, error, partial, and success states in the design system. No surface shall ship without all five states identified, designed, and implemented. The design system shall provide reusable components for each state class so per-surface implementations are consistent.

## Rationale

Most "broken UX" complaints trace to undefined states: blank screens that should be empty states, spinners that hide errors, success toasts that fire on failure. Defining the full state matrix upfront is what separates designed UX from accidentally shipped UX.
