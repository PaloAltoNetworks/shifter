---
id: CTF-1002
title: "Automated Range Spinup"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.775033Z
updated_at: 2026-03-19T04:24:14.741196Z
---

# CTF-1002: Automated Range Spinup

## Statement

The system should automatically trigger range provisioning for all registered participants at a configurable time before the event start (for example 30 minutes before). The spinup task shall use throttled provisioning to avoid overwhelming infrastructure. If provisioning is not complete by event start, the system shall continue provisioning while the event runs and notify organizers of the delay.

## Rationale

Ranges take 10-20 minutes to provision. If provisioning starts at event start time, participants wait with nothing to do. Pre-provisioning ensures ranges are ready when the competition begins. Automation eliminates the need for organizers to manually trigger provisioning at the right time.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py::_schedule_event_tasks` (Schedules SPIN_UP_RANGES task at event.get_spinup_time() when event transitions to SCHEDULED)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py::CTFEvent.range_spinup_minutes,CTFEvent.get_spinup_time` (Configurable range_spinup_minutes field (default 30, 0-1440) and get_spinup_time() method computing event_start - spinup_minutes)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range.py::provision_event_ranges_throttled` (Throttled provisioning - spreads requests across spinup_window_seconds, delay clamped [5,120]s, supports shutdown_check for graceful abort, continues on per-participant failures)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py::_handle_spin_up_ranges` (SPIN_UP_RANGES task handler - dispatches to provision_event_ranges_throttled with spinup_window computed from range_spinup_minutes)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range/provision.py::provision_event_ranges_throttled` (Throttled participant range provisioning used by scheduled spin-up tasks)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_range.py` (Range service tests - scheduled/throttled event range provisioning and participant roster behavior)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
