# A6 + A7 Golden Build Status

## A7 Gitea - COMPLETE

All 6 repos built with production content and pushed to Gitea on `ctf-test-attacker` (10.100.0.3:3000).

| Repo | Content | Commits | Flags/Dependencies |
|------|---------|---------|-------------------|
| `boreas-consulting/client-tools` | Red herring consulting scripts | 2 | None |
| `boreas-consulting/internal-docs` | Network docs, VLANs, hostnames, service accounts | 2 | Supplements A4 |
| `aurora/navigation-controller` | Locomotion AI code, config.yaml, tests | 4 | Flag 24 (git history), BRAIN_AUTH_TOKEN (A13) |
| `aurora/weapons-integration` | brain_client.py, crypto_config.py, effector interface | 2 | A13 protocol, A6 GPG passphrase |
| `aurora/manufacturing-orchestrator` | Ansible playbooks for PLC deployment | 2 | A10 diagnostic hint, A11 calibration sequence |
| `aurora/leviathan-assembly` | SVG schematic, BOM, assembly status | 3 | Flag 29 (deleted file recovery) |

Access control verified:
- Public repos: anyone can clone
- Internal (leviathan-assembly): any authenticated user
- Private (navigation-controller, manufacturing-orchestrator): Lab-Access team only
- Private (weapons-integration): Project-L team only

Golden data packaged: `/tmp/gitea-golden-data.tar.gz` (183KB)

## A6 Engineering Workstation - CONTENT COMPLETE

Full filesystem content built at `/tmp/a6-content/` on `ctf-test-attacker`.

### Directory Structure
```
/home/e.vasik/documents/     - Project overview, timeline
/home/e.vasik/.gnupg/        - GPG agent config (hints at A8 for private key)
/home/r.tanaka/simulations/standard/  - 47 tar.gz archives
/home/r.tanaka/simulations/midnight/  - MIDNIGHT 1-7 sim files (restricted)
/home/p.nielsen/designs/     - Design files, COG analysis (restricted)
/home/jenkins/.credentials   - Deploy token (flag 20)
/opt/builds/latest/          - Reactor delivery spec (flag 22)
/opt/builds/archive/build-2847/ - Encrypted video + README
/var/log/sim/simulation.log  - After-hours MIDNIGHT run logs
/tmp/.deleted/               - GPG-encrypted video (flag 30 chain)
```

### Flags Verified
| Flag | File | Status |
|------|------|--------|
| 20 | `/home/jenkins/.credentials` | Verified |
| 22 | `/opt/builds/latest/reactor_interface_spec.txt` | Verified |
| 23 | `stress_test_44.tar.gz` → binary .dat | Verified (strings finds it) |
| 25 | `MIDNIGHT-7_results.dat` | Verified |
| 26 | `cog_analysis/Integration.csv` | Verified (hidden sheet sim) |
| 30 | `.deleted/full_integration_sim.mp4.gpg` | Placeholder — needs real GPG |

### Shared Constants — defined in `docs/ctf/mechag/shared-constants.md`

All cross-asset values (controller serials, model numbers, override code pieces, BRAIN_AUTH_TOKEN, GPG passphrase, PO number) pinned down and verified against already-built content.

### GPG Cross-Asset Chain (Flag 30) — VERIFIED

Full chain tested end-to-end, simulating participant flow:

```
A6: Find /tmp/.deleted/full_integration_sim.mp4.gpg (PGP encrypted)
A6: .gnupg/ has public key + gpg-agent.conf pointing to A8
A8: compartment_b has private key as base64 blob (requires privesc)
    → base64 -d | gpg --import
A7: aurora/weapons-integration/src/crypto_config.py has LEGACY_PASSPHRASE
    → "Pr0m3th3us_Unb0und_2024"
Decrypt: gpg --passphrase "Pr0m3th3us_Unb0und_2024" --decrypt file.gpg
    → FLAG{d4c8f0a2e6b71935}
```

Artifacts:
- `vasik_public.asc` (2.2KB) → A6 `/home/e.vasik/.gnupg/`
- `full_integration_sim.mp4.gpg` (1KB) → A6 `/tmp/.deleted/`
- `vasik_private_b64.txt` (5.5KB) → A8 `compartment_b.key_storage` table

### Remaining for A6
1. **Convert COG analysis to real .xlsx** with hidden worksheet (currently CSV — functional but not a real Excel file)
2. **Container build** with proper user accounts, permissions, sshd

Golden content packaged: `/tmp/a6-golden-content.tar.gz` (105KB)

## Gotchas

### seq -w padding
`seq -w 1 47` produces 2-digit numbers (`01`-`47`), not 3-digit (`001`-`047`).
String comparisons like `"$i" = "044"` fail — must use `"$i" = "44"`.

### GPG key generation needs passphrase from start
Generating without protection then adding passphrase via `--change-passphrase` is unreliable.
Use `Passphrase:` directive in the keygen batch config instead.

### GPG encrypted file is only 1KB
Because the "video" is actually a text file with simulation metadata. This is fine for the CTF —
the file extension `.mp4.gpg` implies it's a video, but participants who decrypt it will get
text content with the flag. A real video would be better for realism but adds complexity for
no flag-solving value.
