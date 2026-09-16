---
id: CTF-1003
title: "Automated Range Cleanup"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.819431Z
updated_at: 2026-03-19T03:06:02.600119Z
---

# CTF-1003: Automated Range Cleanup

## Statement

The system should automatically destroy all range instances associated with an event after a configurable delay following event end (default 2 hours). The cleanup task shall destroy ranges in batches to avoid API throttling. The system shall send a warning notification to participants before cleanup begins. Organizers shall be able to cancel or defer automated cleanup.

## Rationale

Post-event cleanup is the most commonly forgotten manual task, leading to ranges running for days after an event ends. Automated cleanup with a grace period (for post-event review) balances cost control with usability. The warning notification gives participants time to save any work before their environment is destroyed.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py::CTFEvent.cleanup_delay_hours,CTFEvent.auto_cleanup,CTFEvent.get_cleanup_time` (Configurable cleanup_delay_hours (default 24, 1-168), auto_cleanup toggle, get_cleanup_time() method computing event_end + delay)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range.py::cleanup_event_ranges` (Destroys all ranges for an event - iterates participants with ranges, calls _destroy_single_range, tracks destroyed/failed counts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py::_handle_cleanup_ranges` (CLEANUP_RANGES task handler - dispatches to cleanup_event_ranges)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py::_schedule_event_tasks(CLEANUP_RANGES)` (Schedules CLEANUP_RANGES task at get_cleanup_time() when auto_cleanup is enabled)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#628` (CTF-1003: Automated Range Cleanup)
