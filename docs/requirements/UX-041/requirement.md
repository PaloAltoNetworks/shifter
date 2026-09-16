---
id: UX-041
title: "Bundle size budgets"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:39:02.769872Z
updated_at: 2026-05-09T04:39:02.769872Z
---

# UX-041: Bundle size budgets

## Statement

JavaScript and CSS bundle sizes per surface shall have documented budgets enforced in continuous integration. Pull requests that exceed a budget shall fail unless the budget is updated with rationale in the same change.

## Rationale

Bundle size is the upstream cause of most LCP regressions. Tracking it directly catches regressions earlier and keeps the conversation about cost-vs-value at the moment a dependency is added, not months later when the budget is already blown.
