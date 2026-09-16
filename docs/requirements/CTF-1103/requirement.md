---
id: CTF-1103
title: "Event Export"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.036262Z
updated_at: 2026-03-19T03:07:28.770558Z
---

# CTF-1103: Event Export

## Statement

The system could support exporting event results and statistics to CSV or JSON format. The export shall include: final scoreboard rankings, per-participant solve details (challenge, timestamp, points), hint usage, and aggregate event statistics. The export shall be available to organizers after event end.

## Rationale

Event result export enables post-event reporting, analysis, and record-keeping. Organizers may need to share results with management, generate certificates, or analyze participant performance trends across multiple events. Without export, this data is locked in the platform.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py (get_event_statistics)` (Event statistics service - computes stats but no CSV/JSON export function)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#631` (CTF-1103: Event Export)
