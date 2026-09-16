---
id: UX-004
title: "Design artifacts versioned with code"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:40.416267Z
updated_at: 2026-05-09T04:37:40.416267Z
---

# UX-004: Design artifacts versioned with code

## Statement

Wireframes, mockups, design system source, and visual identity assets shall live where they can be reviewed against the implementation by anyone with repo access, including OSS contributors who do not have access to vendor-locked design tools. The design system shall be discoverable from the repository root.

## Rationale

Design that lives in one person's account or a vendor-locked tool is opaque to OSS contributors and silently drifts from the implementation. For Shifter to ship as OSS, the design must be inspectable, reviewable, and forkable alongside the code.
