---
id: UX-022
title: "Plain-language error and empty messaging"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:38:33.954289Z
updated_at: 2026-05-09T04:38:33.954289Z
---

# UX-022: Plain-language error and empty messaging

## Statement

User-facing copy shall be plain-language. Error messages shall describe what went wrong in user terms and, where possible, what the user can do next. Stack traces, raw exception strings, internal field names, and backend identifiers shall not appear in the UI. Empty states shall explain why the surface is empty and what the user can do to populate it.

## Rationale

Error and empty states are where users feel friction most acutely. Defaulting to backend strings in the UI is a tell-tale sign of an undesigned product and actively misleads users (they often can't distinguish a transient error from a permanent one).
