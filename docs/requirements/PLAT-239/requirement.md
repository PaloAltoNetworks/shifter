---
id: PLAT-239
title: "Workspace resource quotas and usage"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
created_at: 2026-08-01T17:37:36.027203Z
updated_at: 2026-08-01T17:41:19.898050Z
---

# PLAT-239: Workspace resource quotas and usage

## Statement

The platform shall support per-workspace resource limits (for example concurrent ranges and member seats) with server-side enforcement, plus an SPA surface that displays usage against limits. Limits shall be soft- or hard-capped per policy, and quota decisions shall be recorded so administrators can see when and why a limit was applied.

## Rationale

Shared infrastructure such as a university or lab needs guardrails on cost and capacity; without per-workspace quotas a single workspace can exhaust the deployment. Recording quota decisions gives administrators visibility into enforcement.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1946`
