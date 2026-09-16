---
id: UX-032
title: "Progressive enhancement for read-only views"
status: DRAFT
type: NON_FUNCTIONAL
priority: COULD
created_at: 2026-05-09T04:38:54.030422Z
updated_at: 2026-05-09T04:38:54.030422Z
---

# UX-032: Progressive enhancement for read-only views

## Statement

Read-only participant views, scoreboard, challenge listing, public documentation, shall be usable when JavaScript is unavailable. Interactive features may degrade, but content shall remain accessible and the page shall not rely on JS to render its primary content.

## Rationale

Progressive enhancement is a resilience property: the page works for users behind restrictive networks, with broken JS bundles, or using assistive tech that doesn't execute scripts well. It also forces a separation between "content" and "interactivity" that improves the architecture.
