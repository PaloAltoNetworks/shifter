---
id: CTF-004
title: "Scoreboard & Rankings"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.012281Z
updated_at: 2026-04-04T16:36:19.374295Z
---

# CTF-004: Scoreboard & Rankings

## Statement

The system shall present a live scoreboard that ranks participants by score, provides visibility into competition progress, and supports organizer controls over what ranking information is displayed and when.

## Rationale

The scoreboard is the primary competitive interface, participants check it constantly to gauge their standing. Scoreboard freeze near event end maintains suspense. A polished, real-time scoreboard is essential for engagement. The scoreboard is delivered as a CTF view within Mission Control's UI layer, and real-time updates should leverage the platform's WebSocket infrastructure (PLAT-105) when available.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/services/scoring.py` (Scoring service: scoreboard generation, ranking, score calculation)
- IMPLEMENTS → CODE_FILE `ctf/views.py` (CTF views: participant scoreboard, admin scoreboard, and scoreboard API endpoint)
- IMPLEMENTS → CODE_FILE `templates/ctf/participant/scoreboard.html` (Participant scoreboard template with auto-refresh polling)
- IMPLEMENTS → CODE_FILE `templates/ctf/admin/scoreboard.html` (Admin scoreboard template with event statistics and rankings)
- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTFEvent model: scoreboard_visible, scoreboard_freeze_at, is_scoreboard_frozen)
- IMPLEMENTS → CODE_FILE `ctf/services/event.py` (Event service: scoreboard_visible in mutable fields whitelist)
- IMPLEMENTS → CODE_FILE `ctf/forms.py` (CTFEventForm: scoreboard_visible field for organizer controls)
- IMPLEMENTS → CODE_FILE `ctf/migrations/0021_add_scoreboard_visible.py` (Migration: add scoreboard_visible field to CTFEvent)
- IMPLEMENTS → CODE_FILE `templates/ctf/admin/event_form.html` (Event form template: scoreboard visibility checkbox for organizers)
- IMPLEMENTS → CODE_FILE `ctf/urls.py` (URL routing for scoreboard views and API endpoints)
- IMPLEMENTS → CODE_FILE `templates/ctf/includes/scoreboard_table.html` (Reusable participant scoreboard table rows include)
- IMPLEMENTS → CODE_FILE `static/js/score-timeline.js` (Score timeline Chart.js visualization for competition progress)
- TESTS → TEST `tests/ctf/test_scoring.py` (Tests for scoreboard ranking, freeze logic, and visibility controls)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#576` (CTF-004: Scoreboard & Rankings)
