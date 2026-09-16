---
id: PLAT-215
title: "LLM Runtime, Prompt, Token, and Cost Metering"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-05-09T06:03:34.475991Z
updated_at: 2026-05-09T06:03:34.475991Z
---

# PLAT-215: LLM Runtime, Prompt, Token, and Cost Metering

## Statement

The platform shall expose a common runtime contract for LLM-backed experiment or range agents across configured providers, preserving provider, model, prompt variant, rendered prompt, tool-use mode, token usage, call latency, and estimated cost per run. Metering shall be aggregated by run, experiment condition, event, and range where that context exists.

## Rationale

PLAT-202 covers credential plumbing and shardable LLM access, but Shifter also needs the measurement and cost-governance side identified by LilRAE (formerly APTL): provider abstraction, prompt capture, token usage, latency, and estimated spend.

## Traceability

- DOCUMENTS → SPEC `aptl:EXP-003` (LilRAE specification, former APTL identifier EXP-003: Multi-Provider LLM Runtime)
- DOCUMENTS → SPEC `aptl:EXP-004` (LilRAE specification, former APTL identifier EXP-004: Per-Run LLM Token and Cost Metering)
- DOCUMENTS → SPEC `aptl:EXP-005` (LilRAE specification, former APTL identifier EXP-005: System Prompt Parameterization for Experiments)
- DOCUMENTS → DOCUMENTATION `scenario-dev/polaris/lessons-2.md` (Polaris lessons: Bedrock cost and token metering)
- DOCUMENTS → DOCUMENTATION `scenario-dev/polaris/lessons-1.md` (Polaris lessons: event Bedrock cost exposure)
