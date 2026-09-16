---
id: UX-017
title: "Color scheme preference honored"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:38:20.932544Z
updated_at: 2026-05-09T04:38:20.932544Z
---

# UX-017: Color scheme preference honored

## Statement

The platform shall honor the prefers-color-scheme CSS media query, supporting both light and dark themes. Both themes shall be built from the same design-system token set so visual decisions stay coherent and a third theme (for example high-contrast) can be added by extending the token system rather than by forking templates.

## Rationale

Dark mode is a baseline expectation for modern web applications and is significant for users with low vision and light sensitivity. Building both themes from a shared token system also enforces design discipline: a value that can't be expressed as a token is a hint that the design system has a gap.
