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

Running Polaris at Ottawa BSides required operators to stand up CTFd, a briefing site, and several static content surfaces by hand, each step a bespoke script, each handoff prone to drift from the scenario's expected configuration. Participant ranges already deploy cleanly through the existing per-participant provisioning path, but the non-range event-scoped surfaces have no platform-level analogue. Event runners with a working Shifter instance should be able to choose a scenario and click to spin up everything the scenario needs, not just the participant VMs. This is distinct from per-participant range provisioning (CTF-901) and from CTFd feature parity, those are already covered. This requirement is about making the deployment of event-scoped supporting assets a platform capability.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#669` (CTF-909: Event-Specific Asset Deployment)
