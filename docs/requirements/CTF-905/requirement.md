---
id: CTF-905
title: "Throttled Range Provisioning"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.610402Z
updated_at: 2026-04-16T22:50:02.449528Z
---

# CTF-905: Throttled Range Provisioning

## Statement

The CTF layer should pace range provisioning requests to avoid overwhelming the Engine's provisioning pipeline. Provisioning shall be spread across a configurable time window with a configurable delay between requests, clamped to safe bounds. Throttling is implemented as CTF-layer orchestration that calls cms.services.create_range() at a controlled rate, it does not modify the Engine or CMS provisioning internals. The system shall report provisioning progress (for example 15/50 ranges ready).

## Rationale

Provisioning many range instances simultaneously creates a thundering herd against cloud APIs and the provisioning pipeline. Rate limits, resource contention, and state locks can cause cascading failures. Throttling spreads the load over time, trading speed for reliability. This is a learned operational requirement from running Shifter at scale. Note: CTF-905 provides CTF-layer-side static pacing only, it has no mechanism to signal overall event shape to the provisioner, and it does not cover shared non-compute resources (Bedrock throughput, cross-account IAM capacity, NAT bandwidth). Those concerns are addressed by CTF-908 (Event Capacity Declaration) and PLAT-201 (Capacity-Aware Provisioning).

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py` (_handle_spin_up_ranges() - Scheduler integration for throttled provisioning)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py::CTFEvent.range_spinup_minutes` (CTFEvent.range_spinup_minutes - Per-event configurable spinup window)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_range.py` (TestProvisionEventRangesThrottled - Throttled provisioning test suite)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#571` (CTF-905: Throttled Range Provisioning)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range/batch.py` (provision_event_ranges_throttled() - throttled range provisioning)
