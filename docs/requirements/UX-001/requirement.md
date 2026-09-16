---
id: UX-001
title: "Design system as single source of truth"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:23.891718Z
updated_at: 2026-05-09T04:37:23.891718Z
---

# UX-001: Design system as single source of truth

## Statement

The platform shall maintain a single repo-wide design system as the only legitimate source of visual decisions. The design system shall include documented tokens (color, typography, spacing, radius, motion), a typography scale, a base component inventory, and usage guidelines for each component. Per-app or ad-hoc styling that bypasses the design system shall be rejected at review.

## Rationale

Today the frontend has five separate Django apps with independent base templates and an explicit XDR/Cortex theme stylesheet. Visual decisions are scattered across templates and CSS files with no shared vocabulary, which produces drift between surfaces and makes a coherent OSS rebrand impossible without a unified system to migrate to. A design system is the foundation every other UX requirement depends on.
