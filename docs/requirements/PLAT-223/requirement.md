---
id: PLAT-223
title: "RBAC for Egress Allowlist Management"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-13T16:32:20.425603Z
updated_at: 2026-05-13T16:32:20.425603Z
---

# PLAT-223: RBAC for Egress Allowlist Management

## Statement

Management of platform-level allowlists and named allowlist sets (PLAT-220, PLAT-222) shall be gated by role-based access control. Permissions shall distinguish read (view current platform / scenario effective allowlist), author (create or edit named sets), and apply (change the platform default or assign sets to scenarios). Scenario-level overrides (PLAT-221) shall be subject to the existing scenario authoring RBAC, with the platform retaining the ability to forbid scenarios from broadening egress beyond an admin-defined ceiling.

## Rationale

Egress allowlists are a security control. Without RBAC any scenario author or operator with edit access can broaden egress and, by extension, the blast radius of a range. RBAC separates "view current policy" (broad), "author a set" (curated authors), and "change what production ranges actually use" (platform admins). The ceiling clause keeps scenario authors from bypassing platform policy via unbounded additive overrides. Refines PLAT-220 by attaching access control to the configuration surface.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#778` (PLAT-223: RBAC for Egress Allowlist Management)
