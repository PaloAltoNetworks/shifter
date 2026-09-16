---
id: CTF-706
title: "Event Cancellation"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:23.257931Z
updated_at: 2026-03-19T03:08:13.512253Z
---

# CTF-706: Event Cancellation

## Statement

The system shall support cancelling events from any pre-ended state (draft, registration, active, paused). Cancellation shall: transition the event to a cancelled state, trigger cleanup of all provisioned resources, send cancellation notifications to all registered participants, and prevent further submissions. Cancelled events shall be visible in event history but not in active listings.

## Rationale

Events get cancelled due to insufficient registrations, scheduling conflicts, or infrastructure issues. Without a cancellation flow, organizers must manually notify participants and clean up resources. The cancelled state preserves audit trail while clearly distinguishing from normally ended events.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#662` (CTF-706: Event Cancellation)
