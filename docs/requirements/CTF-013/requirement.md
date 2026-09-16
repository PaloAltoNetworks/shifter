---
id: CTF-013
title: "Administration"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.341312Z
updated_at: 2026-03-26T06:34:21.005018Z
---

# CTF-013: Administration

## Statement

The CTF layer shall provide organizers with administrative dashboards and analytics delivered through Mission Control's UI layer, giving operational visibility into running events and historical performance data.

## Rationale

Organizers need operational visibility into running events, who is stuck, which challenges are too easy or too hard, whether ranges are healthy. Without administrative dashboards, organizers operate blind during events and cannot make real-time adjustments like releasing hints or extending time. CTF admin views are delivered within Mission Control, leveraging existing UI patterns and access controls.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::admin_dashboard` (Admin dashboard view - organizer overview with event stats)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::admin_analytics` (Admin analytics view - per-event and per-challenge statistics)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::admin_event_detail` (Event detail view - real-time stats, status controls, management links)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::admin_scoreboard` (Admin scoreboard view - live rankings with participant/team scores)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::admin_range_list` (Admin range list view - range provisioning status per participant)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py::get_event_statistics` (Event statistics service - participant count, submissions, points)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py::get_challenge_statistics` (Challenge statistics service - solve count, solve rate, first blood)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py::get_event_stats` (Event stats service - participants, challenges, submissions, points)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/dashboard.html` (Admin dashboard template - stats cards and recent events table)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/analytics.html` (Analytics template - event stats and per-challenge breakdown table)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/event_detail.html` (Event detail template - stats sidebar, status actions, management links)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/scoreboard.html` (Scoreboard template - live rankings with rank, score, solves)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/range_list.html` (Range list template - per-participant range status and provisioning controls)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring/_stats.py::get_challenge_statistics` (Challenge statistics service - event-roster solve-rate denominator, solve count, attempts, first blood)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring_statistics.py` (Challenge statistics tests - roster denominator, attempts, solves, first blood, event scoping)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
