---
id: CTF-902
title: "Range Lifecycle Management"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:23.499978Z
updated_at: 2026-03-26T04:03:27.290990Z
---

# CTF-902: Range Lifecycle Management

## Statement

The system shall manage range instance lifecycle states tied to event state: provision when event becomes active, keep running during active/paused states, and destroy when event ends or is cancelled. Organizers shall be able to manually start, stop, restart, or destroy individual participant ranges. The system shall handle provisioning failures with configurable retry logic and organizer notification upon failure. Range state shall be visible to both the participant and organizer.

## Rationale

Range lifecycle must be tightly coupled to event lifecycle to prevent orphaned resources. Cloud VMs cost money every minute, ranges that outlive their event waste budget. CTFd has no infrastructure concept. Shifter must ensure ranges are created when needed and destroyed when done, with manual overrides for troubleshooting.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/services/range.py` (Range lifecycle service (provision, destroy, cleanup, status))
- IMPLEMENTS → CODE_FILE `ctf/services/event.py` (Event lifecycle service (scheduled tasks for spin-up/cleanup tied to event states))
- IMPLEMENTS → CODE_FILE `ctf/management/commands/run_ctf_scheduler.py` (CTF scheduler - executes SPIN_UP_RANGES, CLEANUP_RANGES, EVENT_START, EVENT_END tasks)
- IMPLEMENTS → CODE_FILE `ctf/views.py` (CTF views - organizer manual provision/destroy APIs, participant/organizer range status views)
- IMPLEMENTS → CODE_FILE `templates/ctf/admin/range_list.html` (Organizer range management UI - status visibility, provision/destroy buttons)
- IMPLEMENTS → CODE_FILE `templates/ctf/participant/range.html` (Participant range status UI - range state visibility for participants)
- IMPLEMENTS → CODE_FILE `ctf/bridges.py` (CTF bridges - stop/start range operations via CMS services)
- IMPLEMENTS → CODE_FILE `ctf/services/notification.py` (Organizer notification on provisioning failure)
- IMPLEMENTS → CODE_FILE `static/js/ctf-ranges.js` (Organizer range UI - stop/start/restart/destroy action buttons)
- TESTS → TEST `tests/ctf/test_services/test_range.py` (Range service tests - provision, destroy, status, cleanup)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#542` (CTF-902: Range Lifecycle Management)
