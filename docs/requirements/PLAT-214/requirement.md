---
id: PLAT-214
title: "Agent Runtime Safety Controls"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-05-09T06:03:34.456476Z
updated_at: 2026-05-09T06:03:34.456476Z
---

# PLAT-214: Agent Runtime Safety Controls

## Statement

When the platform enables LLM-backed or agentic execution inside ranges, it shall provide runtime safety controls including an operator kill switch, configurable autonomy levels, command or tool allow/deny policy, rate limiting, and approval gates for actions classified as dangerous by the deployment policy.

## Rationale

Shifter already records command-execution safety as an architecture NFR and has per-range LLM access requirements. LilRAE (formerly APTL) adds the product-level controls needed when agents can act through tools during experiments or live ranges.

## Traceability

- DOCUMENTS → SPEC `aptl:SAF-001` (LilRAE specification, former APTL identifier SAF-001: Kill Switch for All Agent and MCP Operations)
- DOCUMENTS → SPEC `aptl:SAF-003` (LilRAE specification, former APTL identifier SAF-003: Tiered Autonomy Levels)
- DOCUMENTS → SPEC `aptl:SAF-004` (LilRAE specification, former APTL identifier SAF-004: MCP Command Filtering (Allowlist/Denylist, Rate Limiting))
- DOCUMENTS → SPEC `aptl:SAF-006` (LilRAE specification, former APTL identifier SAF-006: Dangerous Action Approval Workflow)
- DOCUMENTS → DOCUMENTATION `scenario-dev/polaris/lessons-2.md` (Polaris lessons: Bedrock cost and token metering)
- DOCUMENTS → DOCUMENTATION `scenario-dev/polaris/lessons-1.md` (Polaris lessons: event Bedrock cost exposure)
