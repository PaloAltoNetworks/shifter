---
id: CTF-009
title: "Range Integration"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.194389Z
updated_at: 2026-03-19T03:55:47.759542Z
---

# CTF-009: Range Integration

## Statement

The system shall provide each CTF participant with an isolated, browser-accessible cyber range environment whose lifecycle is tied to the event, differentiating Shifter from standalone CTF platforms.

## Rationale

Range integration is what differentiates Shifter CTF from standalone CTFd. CTFd has no concept of lab infrastructure, Shifter provides each participant their own attack/victim environment. This is the core value proposition: turnkey, self-service cyber ranges tied to CTF challenges. Without this integration, participants would need to provision their own labs, defeating the purpose of the platform.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/bridges.py` (Guacamole bridge providing browser-accessible RDP/SSH access to participant ranges)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFEvent and CTFParticipant models with range_status, lifecycle status, and event-bound range fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py` (Event lifecycle management: scheduling, task creation, teardown tied to event lifecycle)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` (Scheduled task executor that polls and dispatches deploy/teardown tasks tying range lifecycle to events)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/signals.py` (Signal handler syncing CMS RangeInstance status changes to CTFParticipant.range_status)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_services/test_range.py` (Unit tests for range provisioning service)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_events.py` (Tests for event lifecycle management including scheduling and teardown)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (Tests for CTF models including range status and lifecycle fields)
- IMPLEMENTS → CODE_FILE `shifter/engine/provisioner/plans/polaris_range_bootstrap.py` (Polaris range bootstrap (provisioner))
- VERIFIES → PULL_REQUEST `836` (security(polaris): close A9 splice-relay credential discoverability gap)
- TESTS → TEST `scenario-dev/polaris/tests/scenario_smoketest/adapters/mission5_bunker.py` (Polaris mission5 bunker smoketest adapter)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range/provision.py` (Per-participant range provisioning (provision_participant_range + retry))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range/batch.py` (Event-level throttled range provisioning (provision_event_ranges_throttled))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/ranges.py` (Range access views and API endpoint (api_range_access) providing participants browser-based range URLs)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/_event_range_lease.py` (CTF event-to-range lease reconciliation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services/_range_lease.py` (Server-owned range lease and expiry lifecycle)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_mid_event_operations.py` (CTF live-event lease rescheduling tests)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_range_expiry_projection.py` (CTF range expiry projection tests)
