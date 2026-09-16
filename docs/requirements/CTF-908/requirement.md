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

CTF-905 provides pacing but has no mechanism to signal event shape in advance. Polaris at Ottawa BSides surfaced this concretely: the provisioner had no way to know that ~110 ranges with heavy agentic Claude usage would stress Bedrock capacity in a single account, forcing an out-of-band operator script (apply_kali_bedrock_shard.py) to shard credentials across accounts. Declaring capacity intent up front lets the provisioner plan (pre-bake additional AMIs, pre-partition cross-account resources, warn on insufficient headroom) rather than react.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#668` (CTF-908: Event Capacity Declaration)
