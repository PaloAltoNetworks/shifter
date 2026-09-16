---
id: CTF-1402
title: "Theming"
status: DRAFT
type: NON_FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.378268Z
updated_at: 2026-03-26T06:35:12.052649Z
---

# CTF-1402: Theming

## Statement

CTF events could support configurable branding including event logo, color scheme, and description. Branding configuration shall be per-event. Visual customization shall be implemented via Django's template system (template context variables and CSS overrides), not a standalone theming engine.

## Rationale

Event branding enables differentiated event experiences, important for events co-hosted with external organizations or customers. Django's template system already supports the template inheritance and context variable patterns needed for per-event visual customization without building a separate theming infrastructure.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF Event model - would need theming/branding fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/base.html` (CTF base template - would need dynamic theme selection)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#639` (CTF-1402: Theming)
