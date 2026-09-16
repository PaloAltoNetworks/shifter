---
id: UX-062
title: "Locale-aware formatting"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:39:32.055352Z
updated_at: 2026-05-09T04:39:32.055352Z
---

# UX-062: Locale-aware formatting

## Statement

Date, time, number, and currency formatting in user-facing surfaces shall honor the user's locale. The platform shall not assume US English conventions (for example MM/DD/YYYY dates, period decimal separators) when rendering values to users.

## Rationale

Hard-coded format strings are a common source of confusion for non-US users (a date `01/02/2026` is ambiguous globally). Django and modern browsers both have first-class locale-aware formatting available; using it is just discipline.
