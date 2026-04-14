# A18: Release Vault

**Status:** Proposed only. Not present in the current build or live range.

**Zone:** Shared
**Type:** Token-gated release manifest and artifact service

## Purpose

This is the second half of the Release Trail mission. Once the participant recovers the leaked token from A17, they can read field rollout metadata and download a field-support bundle. That gives them a believable artifact-inspection task that stays fully outside the current Lab / SCADA / Bunker runtime.

## Configuration

- HTTP(S) artifact service on the shared network
- Directly reachable from Kali
- Bearer-token auth only
- Static manifests and tarballs; no need for a heavyweight registry implementation

## Content

- `/api/releases/latest.json` — latest canary rollout manifest
- `/packages/icebreaker-field-kit-1.7.2.tgz` — downloadable field-support bundle
- `/packages/icebreaker-field-kit-1.7.2.tgz.sha256` — checksum

## Attack Chain

1. Recover `RELEASE_VAULT_TOKEN` from A17.
2. Send `Authorization: Bearer <token>` to read `latest.json`.
3. Learn the current package name and rollout target naming.
4. Download `icebreaker-field-kit-1.7.2.tgz`.
5. Extract the bundle and inspect inventory / config files.
6. Learn about the `splice-relay` field-support concept without bypassing the current bunker path.

## Flags

### Flag 41 — Canary Ring

- **Difficulty:** Medium (100 pts)
- **Location:** `/api/releases/latest.json`. The manifest includes a `tracking_marker` field set to the flag, alongside the current canary release metadata.
- **Flag:** `FLAG{e1c7b4a9d0f26358}`
- **Mission:** Proposed — Release Trail

### Flag 42 — Field Kit

- **Difficulty:** Hard (200 pts)
- **Location:** Inside `icebreaker-field-kit-1.7.2.tgz`, file `inventory/polaris-edge.ini`. The file contains a comment block referencing `splice-relay` and a static flag:
  - `# FIELD_KIT_MARKER=FLAG{6a3f0d8c1e7b4952}`
  The bundle may also include `vpn/splice-relay.ovpn` and `config/channel.yml` to make the field-delivery story feel real.
- **Flag:** `FLAG{6a3f0d8c1e7b4952}`
- **Mission:** Proposed — Release Trail

## Guardrails

- This asset should not expose live bunker addresses, the brain protocol, or the override code.
- The bundle should only foreshadow field-deployed tooling and relay naming.
- Keep the package read-only and self-contained.

## Build Notes

- An nginx or small Flask app is enough here; the mission does not need a full package registry.
- Token auth should be intentionally simple so the challenge focus stays on discovery, not on auth implementation.
- This remains design-only until explicitly approved.

## Cross-Asset Impact If Implemented

- Depends on A17 for the token leak
- Should be reflected in `design/architecture.md`, `design/range-diagram.md`, and `tests/walkthroughs/README.md` only when promoted from proposal to active plan
