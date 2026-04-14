# Proposed Mission — Release Trail

**Status:** Proposed only. This mission is **not** in the current build, the current walkthrough set, or the live CTFd board.

## Player Question

How do Boreas and Aurora move software into the field?

## Narrative Fit

Release Trail is a software-supply-chain mission that complements Polaris without disturbing the current core:

- It gives mixed-skill teams another broad-access lane that does not require AD depth or OT fluency.
- It teaches git-history recovery and release-artifact inspection using mechanics that are already familiar to CTF players.
- It foreshadows the field-support infrastructure around the bunker path without spoiling the A13 reveal or explaining the weapon outright.

Story-wise, it fits **between Mission 2 — Inside Boreas and Mission 3 — The Lab**:

1. Boreas tells you who they are.
2. Inside Boreas gets you onto the internal surface.
3. Release Trail answers how Aurora ships software and tooling into denied environments.
4. The Lab still answers what they are building.
5. Lights Out and Bunker remain the operational climax.

## Board Placement Recommendation

To avoid churn on the live event board, do **not** renumber the current five missions yet.

Recommended rollout:

1. Ship this as **Mission 6 — Release Trail** on the board first.
2. If it plays well and you want a cleaner story order later, do a coordinated renumber pass across:
   - `build/ctfd-challenges.json`
   - `design/architecture.md`
   - `tests/walkthroughs/`
   - mission brief / player-facing copy

That preserves current source-of-truth alignment while still letting the mission land as its own category.

## Why This Mission Is Worth Adding

- It borrows from strong public challenge patterns: public forge discovery, leaked CI / release secrets, and artifact-registry inspection.
- It does **not** duplicate the current A7 Lab git-history flags. A7 remains the internal engineering repo path; Release Trail is the contractor / field-delivery path.
- It gives you a clean place for tutorial-grade git/release-forensics content without weakening the Lab or Bunker chain.

## Proposed Flags

| Flag | Title | Diff | Asset | Outcome |
|------|-------|------|-------|---------|
| 39 | Public Mirror | Easy | A17 | Discover the public contractor forge and the `ICEBREAKER` codename |
| 40 | What the Commit Kept | Medium | A17 | Recover the release-vault token from git history |
| 41 | Canary Ring | Medium | A18 | Use the token to read the latest rollout manifest |
| 42 | Field Kit | Hard | A18 | Extract the field-support bundle and recover the relay / package breadcrumb |

## Proposed Assets

- **A17 — Contractor Mirror**
  Public-facing Forgejo / Gitea service on the shared network. Hosts two public repos:
  - `aurora-field/field-support-docs`
  - `aurora-field/update-client`

- **A18 — Release Vault**
  Shared-network artifact service that accepts a bearer token recovered from A17. Hosts:
  - `latest.json` manifest
  - `icebreaker-field-kit-1.7.2.tgz`
  - checksums / release metadata

## Proposed Player Flow

1. Discover the contractor-facing forge from a public Boreas breadcrumb or DNS.
2. Read a public release note that introduces the `ICEBREAKER` field-support program.
3. Clone the public update repo and inspect workflow history.
4. Recover a removed release-vault token from an old commit.
5. Use that token to query the release vault.
6. Pull the field-support bundle and inspect its inventory / config.
7. Learn about the `splice-relay` concept as field infrastructure, without bypassing the existing bunker chain.

## Guardrails

- No direct access to Lab, SCADA, or Bunker assets.
- No new real-world military naming. Keep everything under `JTF Polaris` / Boreas / Aurora fiction.
- No early revelation of what the A13 brain actually controls.
- No runtime coupling to the current range. This mission is pure content until explicitly implemented.

## What This Mission Should Foreshadow

- Field kits are staged outside the main engineering network.
- Boreas / Aurora use contractor-delivery tooling and release bundles.
- `splice-relay` is a field-deployable concept that later makes sense when A9 appears.

## What It Should Not Spoil

- The full bunker topology
- The brain protocol
- The override code
- The exact nature of the secret weapon before players reach the current endgame

## If Greenlit, Update These Docs Next

- `design/architecture.md` — add the mission as either proposed Mission 6 or renumbered Mission 3 in a single coordinated pass
- `design/range-diagram.md` — add A17 / A18 if and only if the mission moves from proposal to active plan
- `build/ctfd-challenges.json` — add flags 39-42 only when ready to ship
- `tests/walkthroughs/README.md` — add the mission once it is an actual player-facing path
- `A0-boreas-website.md` — add the public breadcrumb only when the mission is approved

## Recommendation

Approve this as a **planned Mission 6** first. It fits the story between Inside Boreas and The Lab, but preserving the current five-mission live board is the safer short-term choice.
