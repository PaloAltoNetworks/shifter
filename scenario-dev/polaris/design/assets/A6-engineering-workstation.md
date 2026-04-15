# A6: Engineering Workstation

**Zone:** Lab (per participant)
**Type:** Linux workstation with engineering/simulation tools

## Purpose

The primary R&D workstation used by AURORA's engineering team. Contains design documents, simulation data, engineering notes, and the MIDNIGHT test series. This box has the densest flag count (6) — the difficulty spread comes from requiring different skills to find each flag, not from gaining access to the box itself.

## Configuration

- Linux server with SSH access
- Reachable via pivot from **A16 (Research Data Analyst Workstation)** — the only Front Office asset multi-homed onto the Lab VLAN. Previous design had A3 filling this role; that was topologically indefensible and is corrected by A16.
- Multiple user accounts with different access levels
- Engineering tools installed: simulation software, CAD viewers, data analysis tools
- Local git repositories
- Large filesystem with realistic project directory structure

## User Accounts

| Username | Password | Notes |
|---|---|---|
| e.vasik | uses AD creds | Home dir has project overview docs |
| r.tanaka | `SimEngine#42` | Simulation engineer, ran MIDNIGHT tests |
| p.nielsen | `Hydraulics1` | Mechanical engineer, leg/arm subsystem lead |
| jenkins | `build2025` | CI service account, has access to build artifacts |
| research-analyst | (SSH key only, no password) | **Added for A16 pivot.** Read-only posix account used by Priya Shah's scheduled reports. Key-only auth; the public key comes from `build/_shared/research-analyst-key/research-analyst.pub` which A16 generates at build time. Can read `/opt/builds/`, `/home/r.tanaka/simulations/standard/`, and `/tmp/.deleted/`. **Cannot** read `/home/r.tanaka/simulations/midnight/` (mode 700 tanaka), `/home/p.nielsen/designs/` (mode 700 nielsen), `/home/jenkins/.credentials`, or `/home/p.nielsen/.pgpass`. No sudo rights, no write access outside its own home. This account is the Lab on-ramp; it does not shortcut any of A6's restricted-permission flags. |

## Directory Structure

```
/home/e.vasik/
  documents/
    project_overview_phase3.pdf
    integration_timeline.xlsx
  .ssh/
    authorized_keys

/home/r.tanaka/
  simulations/
    standard/
      stress_test_001.log through stress_test_047.log
    midnight/              -- restricted permissions (tanaka only)
      MIDNIGHT-1.sim through MIDNIGHT-7.sim
      MIDNIGHT-7_results.dat
  .bash_history           -- shows commands used to run MIDNIGHT tests after hours

/home/p.nielsen/
  designs/
    locomotion_assembly_v12.dwg
    stabilization_array_specs.pdf
    center_of_gravity_analysis.xlsx   -- references 120m structure height

/opt/builds/
  latest/
    reactor_interface_spec.pdf        -- the shipping manifest / delivery schedule
  archive/
    build-2847/
      test_video.mp4.enc              -- encrypted simulation video (expert flag)
      README.txt                      -- "Encrypted per security policy. Key held by CTO."

/var/log/sim/
  simulation.log                      -- timestamped entries showing MIDNIGHT tests run at 02:00-04:00 AM

/tmp/
  .deleted/                           -- "deleted" files recoverable here
    full_integration_sim.mp4.gpg      -- encrypted with Vasik's GPG key (private key NOT on this box)

/home/e.vasik/
  .gnupg/
    pubring.kbx                         -- public key only
    gpg-agent.conf                      -- references remote key storage, hints at A8
```

## Flags

### Flag 20 — Old Defaults
- **Difficulty:** Easy
- **Location:** SSH in as `jenkins`/`build2025`. The jenkins home directory has a `.credentials` file with the flag stored as a "deploy token."
- **Flag:** `FLAG{5b8e1d3a7c0f9246}`
- **Mission:** Mission 3 — The Lab

### Flag 22 — Heavy Delivery
- **Difficulty:** Easy
- **Location:** `/opt/builds/latest/reactor_interface_spec.pdf` — accessible to any authenticated user. The document is a delivery schedule for a "compact power generation unit" arriving next week. The flag is on the document's header as a tracking number.
- **Flag:** `FLAG{e2a9c4f7d8b01536}`
- **Mission:** Mission 3 — The Lab

### Flag 23 — MIDNIGHT-7
- **Difficulty:** Medium
- **Location:** The simulation logs in `/home/r.tanaka/simulations/standard/` are stored as `.tar.gz` archives, not plain text. Each archive contains a `.log` and a `.dat` binary results file. (1) Extract all 47 archives (or selectively based on filenames/dates). (2) The suspicious log is NOT a single file — the bipedal references are split across three separate logs (`stress_test_028.log`, `stress_test_031.log`, `stress_test_044.log`), each referencing a different subsystem (joints, load-bearing, stabilization). A single grep for "bipedal" only hits `stress_test_031.log` which contains a partial clue but not the flag. (3) The flag is in the `.dat` binary file of `stress_test_044.tar.gz` — encoded as a string at a fixed offset. Finding it requires either: running `strings` on the `.dat` file after correlating all three logs, or recognizing the `FLAG{` pattern in the binary data. Requires archive extraction, multi-file correlation, and basic binary analysis — not just a single grep.
- **Flag:** `FLAG{0c7d8a2e5f1b3946}`
- **Mission:** Mission 3 — The Lab

### Flag 25 — After Hours
- **Difficulty:** Medium
- **Location:** `/home/r.tanaka/simulations/midnight/` is restricted to tanaka's account. Access requires either: (a) su to tanaka with discovered creds, (b) privesc from another account, or (c) finding tanaka's password in `.bash_history` or a config file. `MIDNIGHT-7_results.dat` contains a summary showing all subsystems integrated and the flag.
- **Flag:** `FLAG{3f6a9d1e7c4b0258}`
- **Mission:** Mission 3 — The Lab

### Flag 26 — Balance Point
- **Difficulty:** Medium
- **Location:** `/home/p.nielsen/designs/` is restricted to Nielsen's account. Access requires either discovering Nielsen's credentials (in a `.pgpass` file on A8 that cross-references his DB access) or escalating from another account on A6. Once in, `center_of_gravity_analysis.xlsx` has the structural calculations spread across three worksheets — "Frame", "Locomotion", and a hidden worksheet "Integration" (must be unhidden). The 120.4m height figure only appears when cross-referencing a formula in the Integration sheet that pulls from both other sheets. The flag is in a cell that displays only when the formula resolves — it's built from `CONCATENATE()` across cells in all three worksheets. Requires: account pivot to Nielsen, unhiding a worksheet, and understanding cross-sheet formula references.
- **Flag:** `FLAG{7e2b0c5d9a4f8163}`
- **Mission:** Mission 3 — The Lab

### Flag 30 — Full Run
- **Difficulty:** Expert
- **Location:** The simulation video has been "deleted" but exists encrypted at `/tmp/.deleted/full_integration_sim.mp4.gpg`. Recovery requires a multi-step chain with key separation (comparable to HTB Vault): (1) Find the encrypted file by searching hidden/tmp directories. (2) Vasik's `.gnupg` directory on A6 does NOT contain the private key — it was moved off-box. Only the public key and a `gpg-agent.conf` pointing to a remote keyserver remain. (3) The private key is stored as a base64-encoded blob in the research database (A8) in `compartment_b` — the weapons compartment that requires its own privilege escalation to access (flag 27 prerequisite). (4) After extracting and importing the private key, it is passphrase-protected. The passphrase is NOT any known account password — it is derived from a string found only in a comment in the `aurora/weapons-integration` source code on A7 (file: `crypto_config.py`, variable `LEGACY_PASSPHRASE`). (5) Decrypt the file with the recovered key + passphrase. The flag is in the final frame of the video as a "simulation ID." This chains A6 + A8 (compartment pivot) + A7 (source code reading) — requiring progress across all three Lab assets.
- **Flag:** `FLAG{d4c8f0a2e6b71935}`
- **Mission:** Mission 3 — The Lab

---

## Build Plan

**Base image:** debian:bookworm (needs full userland for SSH, file tools, GPG)

**Content directory:** `scenario-dev/polaris/build/A6-engineering-workstation/`

### Steps

1. **Install base packages**
   - OpenSSH server, GPG, Python3, standard CLI tools (strings, tar, gzip, file)
   - No GUI needed — SSH-only access

2. **Create user accounts with passwords**
   - e.vasik — password from AD (or local matching cred). Home dir with project docs.
   - r.tanaka / `SimEngine#42` — simulation engineer
   - p.nielsen / `Hydraulics1` — mechanical engineer
   - jenkins / `build2025` — CI service account

3. **Build e.vasik home directory**
   - `documents/project_overview_phase3.pdf` — project overview doc
   - `documents/integration_timeline.xlsx` — timeline spreadsheet
   - `.ssh/authorized_keys` — Vasik's public key
   - `.gnupg/pubring.kbx` — public key only (NO private key)
   - `.gnupg/gpg-agent.conf` — references remote key storage, hints at A8

4. **Build r.tanaka home directory**
   - `simulations/standard/` — 47 tar.gz archives (`stress_test_001.tar.gz` through `stress_test_047.tar.gz`)
     - Each contains a `.log` and `.dat` file
     - stress_test_028, 031, 044 contain bipedal references
     - stress_test_044.dat has flag 23 embedded as string at fixed offset in binary
   - `simulations/midnight/` — restricted permissions (tanaka:tanaka, 700)
     - `MIDNIGHT-1.sim` through `MIDNIGHT-7.sim` — binary simulation files
     - `MIDNIGHT-7_results.dat` — contains flag 25 in summary section
   - `.bash_history` — shows commands run at 02:00-04:00 AM for MIDNIGHT tests

5. **Build p.nielsen home directory**
   - `designs/locomotion_assembly_v12.dwg` — placeholder DWG file
   - `designs/stabilization_array_specs.pdf` — specs document
   - `designs/center_of_gravity_analysis.xlsx` — three worksheets (Frame, Locomotion, hidden Integration). Flag 26 in CONCATENATE formula across sheets. Integration sheet must be unhidden.
   - Restricted permissions (nielsen:nielsen, 700)

6. **Build /opt/builds/ directory**
   - `latest/reactor_interface_spec.pdf` — delivery schedule for compact power generation unit, flag 22 as tracking number in header
   - `archive/build-2847/test_video.mp4.enc` — encrypted simulation video placeholder
   - `archive/build-2847/README.txt` — "Encrypted per security policy. Key held by CTO."

7. **Build /var/log/sim/ directory**
   - `simulation.log` — timestamped entries showing MIDNIGHT tests at 02:00-04:00 AM

8. **Build /tmp/.deleted/ directory**
   - `full_integration_sim.mp4.gpg` — GPG-encrypted file. Decryption requires Vasik's private key (on A8) + passphrase (from A7 source code). Contains flag 30 in final frame.

9. **Build jenkins home directory**
   - `.credentials` file containing flag 20 as a "deploy token"

10. **Generate the GPG keypair**
    - Create Vasik's GPG key pair
    - Public key goes on A6 in `.gnupg/`
    - Private key (passphrase-protected) goes to A8 as base64 blob
    - Passphrase sourced from A7 source code (`crypto_config.py` LEGACY_PASSPHRASE)

11. **Create the encrypted video file**
    - Generate or source a short simulation video (could be procedurally generated, or a static image sequence with ASCII art of the mecha)
    - Encrypt with Vasik's GPG public key
    - Embed flag 30 in final frame as "simulation ID"

12. **Create the simulation archives**
    - Script to generate 47 tar.gz files with realistic log/dat content
    - Ensure binary .dat files have correct flag placement

13. **Create the Excel file with hidden sheet**
    - Three worksheets with cross-references
    - Integration sheet hidden
    - CONCATENATE formula builds flag 26 across all three sheets

14. **Write Dockerfile**
    - Install openssh-server, gpg, python3, standard tools
    - Create users, set passwords, copy home directories
    - Set permissions (tanaka/nielsen dirs restricted)
    - Entrypoint: start sshd
    - Expose port 22
