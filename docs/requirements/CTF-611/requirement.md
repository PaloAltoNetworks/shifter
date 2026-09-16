---
id: CTF-611
title: "Custom Profile Fields"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T20:39:05.162810Z
updated_at: 2026-03-26T06:10:09.530112Z
---

# CTF-611: Custom Profile Fields

## Statement

CTF events could use the platform's extensible profile fields (PLAT-104) to collect event-specific participant metadata (for example department, experience level, lab tenant). Custom fields on CTF team profiles are CTF-specific and managed within the CTF layer. The CTF layer shall not implement its own custom field infrastructure.

## Rationale

Extensible profile fields are a platform data model capability. CTF uses PLAT-104 for user-level fields and only owns team-level fields (which are CTF-specific entities).

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#659` (CTF-611: Custom Profile Fields)
