---
id: CTF-603
title: "Bulk Participant Import"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.828692Z
updated_at: 2026-03-19T03:08:05.504543Z
---

# CTF-603: Bulk Participant Import

## Statement

The system should support bulk importing participants from a CSV file containing at minimum email addresses and display names. The import shall validate email format, detect duplicates within the file and against existing registrations, and report errors per row without failing the entire import. Successfully imported participants shall be auto-registered for the event.

## Rationale

Bulk import eliminates the need to individually invite dozens of participants. For Shifter enterprise events with 20-50 consultants, organizers typically have a roster spreadsheet. Manual one-by-one invitation is tedious and error-prone at scale.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#652` (CTF-603: Bulk Participant Import)
