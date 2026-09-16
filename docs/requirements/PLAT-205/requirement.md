---
id: PLAT-205
title: "Experiment Run Orchestration"
status: DEPRECATED
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-09T05:11:30.209115Z
updated_at: 2026-08-19T00:00:00Z
---

# PLAT-205: Experiment Run Orchestration

## Statement

The platform shall provide experiment management for repeatable scenario runs, including scripts or prompts assigned to scenario instances, controlled run fan-out, lifecycle states, range provisioning integration, artifact capture, and status/event handling.

## Rationale

Experiment management was implemented as a first-class CMS subsystem. It was removed by ADR-027 (issue #1195): the legacy `cms.experiments` feature was deleted rather than completed, because it never reached end-to-end alpha and is superseded by the RAES-backed direction. This requirement is deprecated and retained as historical record; a future experiment capability requires a new accepted product, security, and data-retention design and must not revive the removed runtime path.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#399` (Add Research VPC and Experiment Management)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#466` (Experiment creation bypasses staff_only and disabled scenario restrictions)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1195` (Legacy experiments removal decision, ADR-027)
- IMPLEMENTS → PULL_REQUEST `780` (Experiment creation enforces staff only and disabled restrictions)
- IMPLEMENTS → ADR `docs/architecture/experiments-removal-adr.md` (ADR-027: legacy experiments removed in favor of a future RAES-backed design)
