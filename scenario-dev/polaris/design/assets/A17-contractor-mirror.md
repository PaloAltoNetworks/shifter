# A17: Contractor Mirror

**Status:** Proposed only. Not present in the current build or live range.

**Zone:** Shared
**Type:** Public Forgejo / Gitea instance for contractor-facing code and release notes

## Purpose

This asset gives Polaris a clean, believable software-supply-chain surface. Boreas and Aurora do not keep every field-facing tool fully internal; a contractor-facing mirror exists for update clients, runbooks, and release notes. That public footprint is exactly the kind of thing a participant can discover early and exploit without needing deep AD or OT knowledge.

## Configuration

- HTTP(S) Git forge on the shared network
- Directly reachable from Kali
- Public read access to two repos
- No dependency on A15, A16, A7, or any other current pivot

## Repositories

| Repo | Visibility | Purpose |
|------|------------|---------|
| `aurora-field/field-support-docs` | Public | Field release notes, rollout notes, contractor docs |
| `aurora-field/update-client` | Public | Source repo whose workflow history leaks the release-vault token |

## Attack Chain

1. Discover the forge host from a public Boreas breadcrumb or DNS.
2. Browse `field-support-docs` and find the latest canary release note for the `ICEBREAKER` program.
3. Clone `update-client` and inspect `.github/workflows/publish.yml` history.
4. Recover a removed `RELEASE_VAULT_TOKEN` and a tracking marker from the deleted workflow lines.
5. Use the token against A18.

## Flags

### Flag 39 — Public Mirror

- **Difficulty:** Easy (50 pts)
- **Location:** Public release note `releases/2025-11-canary.md` in `aurora-field/field-support-docs`. The note introduces the `ICEBREAKER` field-support program. The flag is embedded as a hidden HTML comment at the bottom of the release note.
- **Flag:** `FLAG{9b4e2a1d7c0f5638}`
- **Mission:** Proposed — Release Trail

### Flag 40 — What the Commit Kept

- **Difficulty:** Medium (100 pts)
- **Location:** Git history of `aurora-field/update-client`, file `.github/workflows/publish.yml`. An earlier commit hardcoded:
  - `RELEASE_VAULT_TOKEN=rvlt_7f3d9b1c6e0a42d5b8f14c93a6e2751`
  - `RELEASE_TRACKING_MARKER=FLAG{4d7a1c8e0b3f5926}`
  Recovering the removed lines requires normal `git log -p` or `git show` usage.
- **Flag:** `FLAG{4d7a1c8e0b3f5926}`
- **Mission:** Proposed — Release Trail

## Build Notes

- Reuse the existing Gitea / Forgejo bootstrap pattern from A7 rather than inventing a new forge stack.
- Keep the repos public and self-contained.
- Do not wire this to the current live mission list until approved.

## Cross-Asset Impact If Implemented

- A0 should add a subtle public breadcrumb to the contractor mirror.
- DNS should add the mirror hostname.
- A18 must exist before flag 40 can pay off cleanly.
