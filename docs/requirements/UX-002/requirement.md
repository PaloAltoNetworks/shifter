---
id: UX-002
title: "OSS-friendly visual identity"
status: DRAFT
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:30.339171Z
updated_at: 2026-05-09T04:37:30.339171Z
---

# UX-002: OSS-friendly visual identity

## Statement

The platform's visual identity, including logo, color palette, typography, iconography, voice, and tone, shall be original to OSS Shifter. The codebase, assets, templates, stylesheets, documentation, and any shipped artifact shall not contain Palo Alto Networks trademarks, Cortex or XDR branding, proprietary marks, or proprietary visual assets. This applies to source files, generated assets, social-card images, favicons, and any embedded references.

## Rationale

Palo has agreed to OSS Shifter, but the current frontend embeds Cortex/XDR look-and-feel directly in stylesheets (xdr-theme.css, xdr-sidebar.css, xdr-dropdown.css) and likely elsewhere in templates and copy. Shipping OSS with proprietary brand surface area is both a trademark issue and a clarity issue for downstream contributors. The rebrand is also the opportunity to establish an identity Shifter owns.

## Traceability

- DOCUMENTS → DOCUMENTATION `docs/design/ux-002-oss-visual-identity-preflight.md` (UX-002 OSS Visual Identity Preflight (architecture guardrails for partial debrand))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#718` (Strip Cortex/Palo branding and swap theme to neutral interim (partial UX-002))
