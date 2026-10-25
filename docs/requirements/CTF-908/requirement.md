---
id: CTF-908
title: "Event Capacity Declaration"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-04-16T22:48:07.172236Z
updated_at: 2026-04-16T22:49:36.711007Z
---

# CTF-908: Event Capacity Declaration

## Statement

The CTF layer shall declare event-level capacity attributes to the platform's provisioning engine at event provisioning-plan time, before range spinup begins. Attributes shall include: expected concurrent-range count, participant cohort size, and expected shared-resource demand (including agentic/LLM usage hints such as model/provider class and per-participant rate expectations). These declarations inform the engine's capacity-aware provisioning (see PLAT-201) and shall not be inferred from observation of spinup traffic alone.

## Rationale

Event pacing alone cannot establish whether shared capacity can support an event. Advance declarations let the platform assess model throughput, network capacity, image supply and provisioning concurrency, and report insufficient headroom before launch.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#668` (CTF-908: Event Capacity Declaration)
