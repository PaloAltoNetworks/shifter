---
id: CTF-703
title: "Event Auto-Cleanup"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.151161Z
updated_at: 2026-03-26T06:11:19.205850Z
---

# CTF-703: Event Auto-Cleanup

## Statement

The CTF layer should automatically clean up event resources after the event transitions to ended or cancelled state. Cleanup shall orchestrate Engine range destruction via cms.services.destroy_range() for all participant ranges. Cleanup shall be configurable with a delay (for example 2 hours after event end) to allow post-event review, or immediate on cancellation. Session management is a platform auth concern and not handled by CTF cleanup. The system shall log all cleanup actions.

## Rationale

Forgotten range instances after events are the primary source of unnecessary AWS costs in Shifter. Automatic cleanup ensures cloud resources are released even if organizers forget. CTFd does not manage infrastructure, but Shifter must handle this because each participant has dedicated cloud resources that cost money every minute they run.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTF models - CTFEvent (auto_cleanup, cleanup_delay_hours, get_cleanup_time), CTFScheduledTask)
- IMPLEMENTS → CODE_FILE `ctf/services/event.py` (CTF Event service - _schedule_event_tasks() schedules CLEANUP_RANGES with configurable delay)
- IMPLEMENTS → CODE_FILE `ctf/bridges.py` (CTF bridges - cms_destroy_range() cross-domain integration for range teardown)
- TESTS → TEST `ctf/tests/test_models.py` (Model tests - test_event_get_cleanup_time, auto_cleanup defaults)
- IMPLEMENTS → CODE_FILE `ctf/services/range.py` (CTF Range service - cleanup_event_ranges(), _destroy_single_range())
- IMPLEMENTS → CODE_FILE `ctf/management/commands/run_ctf_scheduler.py` (CTF scheduler - _handle_cleanup_ranges() dispatches cleanup_event_ranges())
- TESTS → TEST `ctf/tests/test_services/test_range.py` (Range service tests - TestCleanupEventRanges, TestDestroyParticipantRange)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#660` (CTF-703: Event Auto-Cleanup)
