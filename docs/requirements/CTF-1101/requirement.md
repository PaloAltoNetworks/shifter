---
id: CTF-1101
title: "Challenge Import"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:23.968994Z
updated_at: 2026-03-19T03:06:45.142514Z
---

# CTF-1101: Challenge Import

## Statement

The system could support importing challenges from a structured file format (JSON or YAML). The import shall create challenges with all supported fields: title, description, category, point value, flags, hints, difficulty, and tags. The import shall validate data integrity and report errors per challenge without failing the entire import. Duplicate detection shall prevent reimporting existing challenges.

## Rationale

Challenge import enables reuse of challenge sets across events and sharing between Shifter instances. Challenge authors often maintain challenge libraries that need to be loaded into new events. Manual recreation of 20+ challenges per event is tedious and error-prone.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (Challenge service - has create_challenge() but no import_challenges() function)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#629` (CTF-1101: Challenge Import)
