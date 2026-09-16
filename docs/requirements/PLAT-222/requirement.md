---
id: PLAT-222
title: "Composable Egress Allowlist Sets with Admin UI"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-13T16:32:13.183444Z
updated_at: 2026-05-13T16:32:13.183444Z
---

# PLAT-222: Composable Egress Allowlist Sets with Admin UI

## Statement

The platform shall let administrators define named, reusable egress allowlist sets (for example `agentic-LLM endpoints`, `corporate-DNS`, `package-mirrors`) and compose them, by inclusion or union, into the platform default and scenario-level allowlists (PLAT-220, PLAT-221). Administrators shall be able to create, edit, version, retire, and inspect these sets through the admin UI. Composition shall resolve deterministically at provisioning time, and an effective-allowlist preview shall be available before changes are applied.

## Rationale

Hand-maintaining flat CIDR lists per scenario and per platform deployment does not scale and rots quickly, provider IPs change, services come and go, and Terraform PRs for every shift become a tax on operators. Named, reusable sets let operators encode intent once ("Bedrock endpoints in us-east-2") and reference it from many places. Admin UI management keeps the workflow inside the product rather than requiring git PRs against infrastructure code every time an upstream IP block changes. Refines PLAT-220 by giving the configuration surface a manageable, composable shape.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#777` (PLAT-222: Composable Egress Allowlist Sets with Admin UI)
