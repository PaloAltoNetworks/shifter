---
id: CTF-1102
title: "Challenge Export"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.002432Z
updated_at: 2026-03-19T03:07:17.633591Z
---

# CTF-1102: Challenge Export

## Statement

The system could support exporting challenges from an event to a structured file format (JSON or YAML). The export shall include all challenge fields, associated hints, and file attachment references. The export shall not include participant submissions or scores. Organizers shall be able to export all challenges or a filtered subset.

## Rationale

Challenge export enables backup, sharing, and migration of challenge content between events and Shifter instances. Combined with import, it creates a complete challenge lifecycle management capability. Export also serves as documentation of event content for post-event review.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (Challenge service - no export_challenges() function exists)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#630` (CTF-1102: Challenge Export)
