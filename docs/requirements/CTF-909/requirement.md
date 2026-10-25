---
id: CTF-909
title: "Event-Specific Asset Deployment"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-04-16T23:59:57.597833Z
updated_at: 2026-04-16T23:59:57.597833Z
---

# CTF-909: Event-Specific Asset Deployment

## Statement

The platform shall support one-click deployment of event-specific supporting assets from the CTF event page. Supporting assets are scenario-specific participant-facing surfaces that are not participant ranges themselves, including but not limited to: scoreboard/challenge servers (for example CTFd), briefing/mission-portal sites, shared static content hosts, and out-of-band landing pages. Scenario packages shall declare which supporting assets they require and how each one is parameterized per event; organizers shall be able to deploy, redeploy, and destroy each supporting asset independently of participant ranges, with lifecycle tied to the event. Supporting assets shall be isolated per event so two concurrent events running the same scenario do not share or collide on asset state.

## Rationale

Event-scoped supporting services need an installation lifecycle alongside participant ranges. Organizers should be able to install the supporting assets declared by an external pack through tenant administration, with explicit authorization and observable outcomes.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#669` (CTF-909: Event-Specific Asset Deployment)
