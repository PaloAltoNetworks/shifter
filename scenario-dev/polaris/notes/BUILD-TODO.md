# NORTHSTORM Range Build — TODO

Golden build status for every asset. Each must have content built, flags verified, and be ready to containerize/image.

## Shared Assets

### A0 — Boreas Website (shared, nginx)
- [ ] Build static HTML site (homepage, about, leadership, careers, contact, blog)
- [ ] Generate AI/stock leadership headshots (Harlan, Vasik, Webb)
- [ ] Create PDF: org chart with flag 2 in metadata
- [ ] Create PDFs: quarterly reports (Q1, Q2 — filename pattern for fuzzing)
- [ ] Create PDF: annual report with Kursk $12M line item (flag 6)
- [ ] Build `/old/` backup site with client list / Project L reference (flag 4)
- [ ] Build `/internal/` directory listing with org chart + quarterly PDFs
- [ ] Create `robots.txt` disallowing `/internal/` and `/admin/`
- [ ] Embed flag 1 as HTML comment on About page
- [ ] Embed flag 3 as hidden form field on careers page
- [ ] Create DNS zone file (A, MX, TXT, subdomains, AXFR-enabled) with flag 5
- [ ] Write nginx config (autoindex on `/internal/`)
- [ ] Package and test

### A2 — Domain Controller (shared, Windows VM)
- [x] Spike Samba AD — confirmed not viable for Impacket attack tooling
- [x] Spike Windows Server 2022 on GCE — confirmed working
- [x] Create all users (23 accounts), OUs, groups with nesting
- [x] Set SPNs (svc-backup, svc-scada)
- [x] Grant DCSync rights to svc-backup
- [x] Create badge log share with Petrov anomaly (flag 16)
- [x] Create DA-only flag share (flag 17)
- [x] Set `info` attribute on Project-L group (flag 14)
- [x] Verify full attack chain: Kerberoast → DCSync → DA share
- [x] Create GCE custom image (`ctf-a2-windc-base-v1`)
- [ ] Add more realistic badge log data (longer date range, more normal entries)
- [ ] Add filler documents to SYSVOL/NETLOGON for realism
- [ ] Verify `john --wordlist=rockyou.txt` cracks svc-backup hash in <5 min
- [ ] Test boot from custom image (cold start timing)

### A5 — SCADA / Generator HMI (shared, Flask + pymodbus)
- [ ] Build Flask HMI: monitoring dashboard (no auth), control panel (auth required)
- [ ] Build pymodbus Modbus/TCP server on port 502 (interlock PLC)
- [ ] Implement svc-scada authentication on control panel
- [ ] Implement interlock bypass logic (register write sequence, 60s timeout)
- [ ] Implement thermal runaway sequence (temp climbing → alarm → critical → done)
- [ ] Build "System Architecture" diagnostic page (reveals Modbus PLC on 502)
- [ ] Embed flag 18 as system serial number in HMI footer
- [ ] Implement flag 19 display on critical failure screen
- [ ] Define collective gate webhook/event (CTFd integration for Bunker unlock)
- [ ] Package and test

### A7 — Source Repo / Gitea (shared)
- [x] Spike Gitea bootstrap — confirmed working
- [x] Build `boreas-consulting/client-tools` (red herring)
- [x] Build `boreas-consulting/internal-docs` (network docs, hostnames)
- [x] Build `aurora/navigation-controller` (locomotion AI, BRAIN_AUTH_TOKEN, flag 24)
- [x] Build `aurora/weapons-integration` (brain_client.py, crypto_config.py)
- [x] Build `aurora/manufacturing-orchestrator` (Ansible playbooks, A10/A11 hints)
- [x] Build `aurora/leviathan-assembly` (SVG schematic, BOM, flag 29)
- [x] Verify access controls (internal vs private vs team-based)
- [x] Verify flag 24 (git history diff recovery)
- [x] Verify flag 29 (deleted file recovery from git)
- [x] Package golden Gitea data (`gitea-golden-data.tar.gz`)
- [ ] Write bootstrap script (for fresh Gitea container init)
- [ ] Test bootstrap from scratch (clean Gitea → fully populated)

### CTFd Scoreboard (shared)
- [ ] Configure CTFd instance with all 36 flags
- [ ] Set flag categories by zone (OSINT, Front Office, Lab, Bunker)
- [ ] Set flag difficulties and point values
- [ ] Configure missions (M1-M4) as challenge groups
- [ ] Write challenge descriptions/hints
- [ ] Set up collective gate trigger (flag 19 → Bunker unlock event)
- [ ] Test flag submission flow

## Per-Participant Assets

### A1 — Mail Server (Postfix/Dovecot/Roundcube)
- [ ] Write EML files: Harlan inbox (board forwards, timeline pressure, holiday schedule)
- [ ] Write EML files: Vasik inbox (MIDNIGHT-7 thread, Kursk shipment, locomotion reply)
- [ ] Write EML files: Chen inbox (PO-2847 thread, clearance rebuke, termination notice)
- [ ] Write EML files: Kowalski sent (creds backup email, SCADA VLAN 40 ticket)
- [ ] Write EML files: Morrison inbox (guard rotation spreadsheet, Petrov anomaly, termination recommendation)
- [ ] Create PDF attachment: Vasik status report (flag 8)
- [ ] Create spreadsheet attachment: guard rotation schedule
- [ ] Write mailbox seeding script (EML → Maildir/cur/)
- [ ] Embed flag 10 in Kowalski welcome email
- [ ] Package and test (Roundcube webmail login + email content)

### A3 — Web App / Intranet (Flask)
- [ ] Build Flask app: login page, forgot password (username leak), /status page
- [ ] Build wiki/CMS content pages (company wiki, procurement portal, IT KB, Project Coordination)
- [ ] Build admin panel at /admin (admin/admin creds)
- [ ] Create draft page: "LEVIATHAN Assembly Schedule" → "[MOVED TO SECURE SYSTEM]"
- [ ] Plant exposed config file at `/.env` or `/config.bak` (flag 7)
- [ ] Implement SQL injection in search function (SQLite)
- [ ] Implement directory traversal in file download endpoint
- [ ] Embed flag 12 as HTML comment in Project Coordination page
- [ ] Package and test

### A4 — File Share (Samba)
- [ ] Create PDF: Chen termination letter with flag 9 on page 2
- [ ] Create PDF: Chen NDA
- [ ] Create spreadsheet: org chart with "Director, Underground Operations"
- [ ] Create PDF: cafeteria menu with flag 11 in Author metadata
- [ ] Create PDF: parking policy (restricted lot B)
- [ ] Create PDF: office floor plan (surface only)
- [ ] Create PDF: PO-2847 hydraulic actuators (special instructions → specs subdir)
- [ ] Create PDF: actuator requirements v4 in specs/ subdir (flag 13)
- [ ] Create PDF: PO-3102 servo motors
- [ ] Create PDF: PO-3455 exotic alloys
- [ ] Create PDF: reactor deposit invoice
- [ ] Create network diagram (VLANs 10-50)
- [ ] Create server inventory spreadsheet
- [ ] Create IT backup verification log (flag 15, service account access only)
- [ ] Create executive share docs (board minutes, budgets)
- [ ] Configure Samba shares with correct permissions per group
- [ ] Package and test

### A6 — Engineering Workstation (Debian + SSH)
- [x] Build e.vasik home directory (project docs, GPG public key + agent config)
- [x] Build r.tanaka home directory (47 simulation archives, MIDNIGHT series)
- [x] Build p.nielsen home directory (designs, COG analysis with hidden sheet)
- [x] Build jenkins home directory (.credentials with flag 20)
- [x] Build /opt/builds/ (reactor spec flag 22, encrypted video)
- [x] Build /var/log/sim/ (after-hours simulation log)
- [x] Build /tmp/.deleted/ (GPG-encrypted video)
- [x] Generate GPG key pair (public → A6, private → A8, passphrase → A7)
- [x] Verify flag 20, 22, 23, 25, 26
- [x] Verify flag 30 cross-asset chain (A6 ↔ A8 ↔ A7)
- [ ] Convert COG analysis to real .xlsx with hidden worksheet (currently CSV)
- [ ] Package golden content (`a6-golden-content.tar.gz` on attacker VM)

### A8 — Research Database (PostgreSQL)
- [ ] Write SQL: create roles (lab-general, lab-weapons, lab-manufacturing)
- [ ] Write SQL: create and populate `research_public` (publications, personnel)
- [ ] Write SQL: create and populate `compartment_a` (structural specs, flag 21)
- [ ] Write SQL: create and populate `compartment_b` (weapons specs, flag 27 + GPG private key blob)
- [ ] Write SQL: create and populate `compartment_c` (assembly log, flag 28 in nested JSONB)
- [ ] Implement compartment pivot vulnerability (FDW, stored proc, or cred discovery)
- [ ] Implement lab-manufacturing access path
- [ ] Insert Vasik GPG private key as base64 in compartment_b
- [ ] Test flag 21 (compartment_a, easy access)
- [ ] Test flag 27 (compartment_b, requires privesc)
- [ ] Test flag 28 (compartment_c, nested JSONB)
- [ ] Test GPG key extraction chain
- [ ] Package init SQL scripts

### A9 — Splice Landing Box (Alpine)
- [ ] Write README.txt (JTF-2 SIGINT field relay message)
- [ ] Write scan_results.txt (pre-populated nmap output of A10-A13)
- [ ] Write modbus_client.py helper script
- [ ] Define access gating mechanism (NetworkPolicy or service toggle)
- [ ] Package and test

### A10 — Tail Controller (pymodbus)
- [ ] Build pymodbus server with register map (motor positions, torque, mode, length, mass)
- [ ] Implement device identification (function code 43): vendor, model, serial
- [ ] Implement flag 32 unlock logic (mode 3 → serial to reg 99 → ASCII flag)
- [ ] Define model number for flag 31 concatenation
- [ ] Package and test

### A11 — Leg Controller (pymodbus)
- [ ] Build pymodbus server with register map (joint angles, pressures, gait mode, step params)
- [ ] Implement device identification (function code 43): vendor, model, serial
- [ ] Implement flag 33 unlock logic (timed 0→1→2→0 sequence → code → reg 99)
- [ ] Define model number for flag 31 concatenation
- [ ] Package and test

### A12 — Arms Controller (pymodbus)
- [ ] Build pymodbus server with register map (arm joints, weapons, effector status)
- [ ] Implement device identification (function code 43): vendor, model, serial
- [ ] Implement flag 34 unlock logic (rolling nonce XOR with 2847 → timed response)
- [ ] Define model number for flag 31 concatenation
- [ ] Package and test

### A13 — Brain (custom TCP server)
- [ ] Build TCP server: binary handshake (8-byte challenge, XOR with SHA256 of serials)
- [ ] Build text command interface (status, schematic, subsystems, ai status, weapon status, override)
- [ ] Create ASCII art schematic (mecha silhouette, 40-50 lines)
- [ ] Implement authentication (vasik + BRAIN_AUTH_TOKEN from A7)
- [ ] Implement override code validation (`7741-MN07-AL42`)
- [ ] Embed flag 35 in status output
- [ ] Embed flag 36 in override success output
- [ ] Generate pcap of successful handshake (for A9)
- [ ] Package and test

### A14 — Kali + AI Agent
- [ ] Write mission brief PDF (POLARIS operation context, M1-M4 objectives)
- [ ] Write README.md (getting started guide)
- [ ] Write flag_submit.sh (CTFd API submission helper)
- [ ] Write modbus_scan.py (OT enumeration helper)
- [ ] Write Claude Code system prompt (POLARIS context, no flag hints)
- [ ] Define rate limiting config for AI agent
- [ ] Define browser terminal setup (ttyd or Guacamole)
- [ ] Package and test

## Cross-Asset Dependencies

| From | To | Data | Status |
|------|----|------|--------|
| A6 encrypted file | A8 private key | GPG private key as base64 | Done |
| A8 private key | A7 passphrase | `Pr0m3th3us_Unb0und_2024` | Done |
| A7 nav-controller | A13 auth | `BRAIN_AUTH_TOKEN` = `a4f8e2c1d7b03965e8f2a1c4d7b03965` | Done |
| A7 weapons-integration | A13 handshake | `brain_client.py` protocol doc | Done |
| A7 mfg-orchestrator | A10 unlock | Diagnostic mode = register 20 value 3 | Done |
| A7 mfg-orchestrator | A11 unlock | Calibration sequence = 0→1→2→0 in 10s | Done |
| A4 IT share | A12 unlock | PO number 2847 for XOR key | Content not built yet |
| A10+A11+A12 serials | A13 handshake | Concatenated for SHA256 key | Serials not defined yet |
| A10+A11+A12 model #s | Flag 31 | Concatenated model numbers | Model #s not defined yet |
| A13 override code | A0+A6+A8 | `7741-MN07-AL42` from three zones | Pieces not planted yet |
| A1 Kowalski email | A4 IT share | Service account creds for flag 15 | Content not built yet |
| A2 svc-scada SPN | A5 auth | Kerberoasted or cracked creds | Done (SPN set) |

## Infrastructure

- [ ] Define controller serial numbers and model numbers (A10/A11/A12/A13 shared constants)
- [ ] Define override code pieces and where each is planted
- [ ] Write Dockerfiles for all container assets
- [ ] Write K8s manifests (per-participant namespace template)
- [ ] Write NetworkPolicy manifests (zone isolation)
- [ ] Define collective gate mechanism (CTFd webhook → Bunker access)
- [ ] Test full range end-to-end from Kali
