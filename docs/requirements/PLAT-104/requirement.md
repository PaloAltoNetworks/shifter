---
id: PLAT-104
title: "Extensible Profile Fields"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 3
created_at: 2026-03-26T06:09:37.484428Z
updated_at: 2026-03-26T06:09:37.484428Z
---

# PLAT-104: Extensible Profile Fields

## Statement

The platform could support admin-defined custom fields on user profiles and other entities. Custom fields shall have a name, field type (text, select, checkbox), and optional validation rules. Custom field values shall be available for display and filtering in admin views. Fields shall be configurable globally or per-context (for example per event).

## Rationale

Multiple platform contexts (CTF events, training sessions, demo environments) benefit from collecting context-specific metadata about users without code changes. Extensible fields are a platform data model capability, not specific to any single feature.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#678` (PLAT-104: Extensible Profile Fields)
