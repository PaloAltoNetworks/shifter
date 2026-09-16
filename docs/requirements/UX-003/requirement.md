---
id: UX-003
title: "Single information architecture across the platform"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:35.746255Z
updated_at: 2026-05-11T01:42:05.151554Z
---

# UX-003: Single information architecture across the platform

## Statement

The platform shall expose a single navigation model spanning CTF, Mission Control, Scenario Editor, Risk Register, and Documentation. Participant and organizer surfaces shall be visually and structurally distinguished. A maintained sitemap and taxonomy shall exist as design artifacts in the repository and shall be updated whenever a new surface is added.

## Rationale

The five Django apps each have their own base template and navigation pattern, producing five mental models for what is logically one platform. New users have to relearn the layout for each app. A single IA, including a clear participant-vs-organizer split, is foundational to making the platform feel like one product rather than five.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#710` (Information architecture & sitemap for the unified platform)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#709` (UX research & personas for OSS Shifter redesign)
- IMPLEMENTS → DOCUMENTATION `docs/design/ux-003-information-architecture-sitemap.md` (UX-003 Information Architecture And Sitemap)
- IMPLEMENTS → PULL_REQUEST `1154` (Add unified platform IA sitemap)
- DOCUMENTS → DOCUMENTATION `docs/design/ux-003-oss-shifter-research-personas.md` (UX-003 OSS Shifter Research Personas)
- CONSTRAINS → ADR `shifter:ADR-013` (Unified platform information architecture uses a shared navigation contract)
