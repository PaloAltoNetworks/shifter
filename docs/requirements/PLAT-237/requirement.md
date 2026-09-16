---
id: PLAT-237
title: "Range-to-workspace scoping administration"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
created_at: 2026-08-01T17:37:27.528393Z
updated_at: 2026-08-01T17:41:19.898041Z
---

# PLAT-237: Range-to-workspace scoping administration

## Statement

The administration surface shall let an authorized administrator view ranges scoped to a workspace and reassign a range's workspace binding, operating on the existing scalar workspace binding carried on CMS request intent, the CMS range projection, and the Engine range, without introducing a cross-layer ForeignKey to the tenancy models and without altering existing per-range owner, lifecycle, or access semantics.

## Rationale

Ranges already carry a scalar workspace binding (PLAT-2011, #1327) but nothing surfaces or lets an administrator manage it. Viewing ranges by workspace and reassigning bindings is needed to actually operate ranges as shared-workspace resources, and it must respect the ADR-046 layer/FK boundary.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1944`
