---
id: CTF-1301
title: "Organizer Dashboard"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:24.203801Z
updated_at: 2026-03-31T03:28:44.047176Z
---

# CTF-1301: Organizer Dashboard

## Statement

The system shall provide an organizer dashboard showing: list of all CTF events with status indicators, quick-access controls for active events (pause, end, announce), participant count and registration status, range provisioning status overview, and recent activity feed (solves, registrations, errors). The dashboard shall be the organizer's primary entry point for CTF management.

## Rationale

Organizers need a single pane of glass for managing CTF events. Without a dashboard, organizers must navigate multiple pages to understand event status. Shifter's dashboard must additionally surface range infrastructure status, which is unique to the platform. (CTFd provides an admin panel for similar event management.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/dashboard.html` (Dashboard template - events, quick controls, range status, activity feed sections)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenges.py` (TestOrganizerDashboard - context, range overview, activity feed, empty state tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#570` (CTF-1301: Organizer Dashboard)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_events.py` (admin_dashboard view - event stats, quick controls, range overview, activity feed)
