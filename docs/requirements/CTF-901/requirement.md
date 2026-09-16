---
id: CTF-901
title: "Per-Participant Range Provisioning"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:23.462051Z
updated_at: 2026-03-26T06:11:01.701812Z
---

# CTF-901: Per-Participant Range Provisioning

## Statement

The CTF layer shall orchestrate per-participant range provisioning by calling the platform's CMS and Engine services. Each registered participant shall receive their own isolated set of VMs (attack box, victim machines) as defined by the event's scenario template. Provisioning shall be triggered at a configurable time before event start or manually by organizers. The CTF layer tracks provisioning status per participant (pending, provisioning, ready, failed) and maps participants to their CMS RangeInstance via a soft reference (integer ID). The CTF layer shall not implement its own provisioning logic, it delegates to cms.services.create_range().

## Rationale

Per-participant ranges are Shifter's core differentiator from CTFd. Each participant needs their own isolated environment to practice attacks without interfering with others. Shared environments create contention and allow participants to see each other's work. This is the fundamental capability that makes Shifter a cyber range platform rather than just a CTF scoreboard.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTFParticipant model with range_instance_id and range_status fields)
- IMPLEMENTS → CODE_FILE `ctf/management/commands/run_ctf_scheduler.py` (Scheduler command executing SPIN_UP_RANGES tasks at configurable time before event start)
- IMPLEMENTS → CODE_FILE `ctf/views.py` (API endpoints for manual provisioning triggers and range status queries)
- IMPLEMENTS → CODE_FILE `ctf/signals.py` (Signal handler syncing range_status (including failed) from CMS to CTFParticipant)
- IMPLEMENTS → CODE_FILE `shared/enums.py` (ResourceStatus enum defining PENDING, PROVISIONING, READY, FAILED states)
- IMPLEMENTS → CODE_FILE `ctf/bridges.py` (Bridge module for CMS range creation, status polling, and destruction)
- IMPLEMENTS → CODE_FILE `cms/handlers.py` (CMS event handler propagating range status (including FAILED) via CTF signal bridge)
- IMPLEMENTS → CODE_FILE `ctf/services/range.py` (Range provisioning service (per-participant and bulk provisioning, status tracking))
- TESTS → TEST `ctf/tests/test_services/test_range.py` (Range service tests covering provisioning, status tracking, and failure handling)
