---
id: UX-040
title: "Core Web Vitals budgets"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:38:58.951703Z
updated_at: 2026-05-09T04:38:58.951703Z
---

# UX-040: Core Web Vitals budgets

## Statement

Representative participant pages shall meet Core Web Vitals targets: Largest Contentful Paint ≤ 2.5 s, Interaction to Next Paint ≤ 200 ms, Cumulative Layout Shift ≤ 0.1. Targets shall be measured against a slow-3G + mid-tier mobile profile. Continuous integration shall fail when a pull request regresses any of these metrics beyond a documented tolerance.

## Rationale

Core Web Vitals are the de-facto industry standard for perceived performance, used by Google in search ranking and by every modern performance tool. Treating them as enforceable budgets, not vibes, is what prevents the slow gradual decay typical of frontends without a perf gate.
