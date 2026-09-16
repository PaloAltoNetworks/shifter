---
id: CTF-704
title: "Event Force Delete"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.188146Z
updated_at: 2026-04-05T01:48:53.958800Z
---

# CTF-704: Event Force Delete

## Statement

The system should support force-deleting an event and all associated resources regardless of event state. Force delete shall cascade to: all range instances (destroyed immediately), all participant registrations, all challenge data, all submissions and scores, and all scheduled tasks. Force delete shall require explicit confirmation including typing the event name. The action shall be logged with the actor and timestamp.

## Rationale

Force delete is the nuclear option for events that need to be completely removed, failed test events, cancelled events with provisioned resources, or events created in error. Without force delete, organizers must manually clean up each resource type, and orphaned ranges continue accruing costs.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py (delete_event)` (delete_event() - soft-delete only, no force-delete or cascade logic)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py (force_delete_event)` (force_delete_event() - service function for force-deleting events with cascade)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py (admin_event_force_delete, api_force_delete_event)` (Admin view and API endpoint for force-deleting events)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (URL patterns for force-delete admin view and API endpoint)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/event_force_delete.html` (Force-delete confirmation page with name-typing confirmation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/event_detail.html` (Danger zone section linking to force-delete page)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_events.py` (Force delete service, API, and admin view tests (16 test cases))
