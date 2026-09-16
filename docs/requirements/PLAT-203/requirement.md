---
id: PLAT-203
title: "Risk Register and Audit Trail"
status: DEPRECATED
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-09T05:11:30.140971Z
updated_at: 2026-07-26T04:51:48.818003Z
---

# PLAT-203: Risk Register and Audit Trail

## Statement

The platform shall provide a risk register for tracking security and operational risks with severity, lifecycle status, STRIDE metadata, comments, soft deletion and restoration, API key access where appropriate, and audit events for auditable changes.

## Rationale

Risk register and audit logging are implemented platform features but were not represented in the shifter requirement set.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#559` (Architecture review: make audit logging durable or explicitly degraded instead of swallowing failures)
- IMPLEMENTS → PULL_REQUEST `731` (Audit Logging)
- IMPLEMENTS → GITHUB_ISSUE `151` (Issue #151)
