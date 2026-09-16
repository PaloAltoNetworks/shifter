---
id: CTF-1304
title: "Event Statistics"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:24.309212Z
updated_at: 2026-03-25T05:51:20.877283Z
---

# CTF-1304: Event Statistics

## Statement

The system should track and display event-level statistics including: total registered participants, active participants (at least one submission), total challenges, challenges with zero solves, average score, median score, total flag submissions (correct and incorrect), and event duration. Statistics shall update in real-time during active events and be preserved after event end.

## Rationale

Event statistics provide the raw data that the organizer dashboard and analytics dashboard consume. They also serve as quick health indicators during live events, zero solves after an hour might indicate broken challenges. Statistics form the foundation for all reporting and analysis features.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (get_event_statistics() - event-level stats (participant counts, challenge count, submissions, points))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py` (get_event_stats() - additional event stats used in admin views)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring.py` (TestGetEventStatistics - tests for all event-level statistics)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#541` (CTF-1304: Complete Event Statistics implementation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_events.py` (admin_analytics view - renders event_stats from get_event_statistics())
