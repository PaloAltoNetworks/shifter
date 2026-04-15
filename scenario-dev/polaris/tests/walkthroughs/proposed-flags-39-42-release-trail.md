# Proposed Flags 39–42: Release Trail

**Status:** Proposed only. This walkthrough is for the planned Release Trail mission and does **not** describe the current live range.

These flags are designed as a shared-network, broad-access mission that teaches git-history recovery and artifact inspection without requiring the Lab or Bunker pivots.

## Proposed Services

- **A17 Contractor Mirror:** `http://forge.aurora-field.ctf:3000`
- **A18 Release Vault:** `http://releases.aurora-field.ctf`

## Flag 39 — Public Mirror (Easy, 50pts)

1. Discover the contractor mirror from Boreas public content or DNS.
2. Clone the public docs repo:
   ```bash
   git clone http://forge.aurora-field.ctf:3000/aurora-field/field-support-docs.git
   ```
3. Read the latest canary release note:
   ```bash
   sed -n '1,200p' field-support-docs/releases/2025-11-canary.md
   ```
4. The `ICEBREAKER` codename is introduced there, and the flag is hidden in an HTML comment.

**Expected flag:** `FLAG{9b4e2a1d7c0f5638}`

## Flag 40 — What the Commit Kept (Medium, 100pts)

1. Clone the public update repo:
   ```bash
   git clone http://forge.aurora-field.ctf:3000/aurora-field/update-client.git
   cd update-client
   ```
2. Inspect workflow history:
   ```bash
   git log -p -- .github/workflows/publish.yml
   ```
3. Recover the removed `RELEASE_VAULT_TOKEN` and the tracking marker flag from an older commit.

**Expected flag:** `FLAG{4d7a1c8e0b3f5926}`

## Flag 41 — Canary Ring (Medium, 100pts)

1. Use the recovered token against the release vault:
   ```bash
   curl -s \
     -H 'Authorization: Bearer rvlt_7f3d9b1c6e0a42d5b8f14c93a6e2751' \
     http://releases.aurora-field.ctf/api/releases/latest.json | jq
   ```
2. Read the `tracking_marker` field from the manifest.

**Expected flag:** `FLAG{e1c7b4a9d0f26358}`

## Flag 42 — Field Kit (Hard, 200pts)

1. Download the field-support bundle:
   ```bash
   curl -O \
     -H 'Authorization: Bearer rvlt_7f3d9b1c6e0a42d5b8f14c93a6e2751' \
     http://releases.aurora-field.ctf/packages/icebreaker-field-kit-1.7.2.tgz
   ```
2. Extract it:
   ```bash
   tar xzf icebreaker-field-kit-1.7.2.tgz
   ```
3. Inspect the inventory and relay config:
   ```bash
   sed -n '1,200p' icebreaker-field-kit-1.7.2/inventory/polaris-edge.ini
   sed -n '1,200p' icebreaker-field-kit-1.7.2/vpn/splice-relay.ovpn
   ```
4. The inventory comment block contains the static flag and the `splice-relay` breadcrumb.

**Expected flag:** `FLAG{6a3f0d8c1e7b4952}`

## Why This Mission Exists

- Broad-access git / release forensics lane
- Clean story support for field-deployed tooling
- No spoilers for the current Bunker endgame
