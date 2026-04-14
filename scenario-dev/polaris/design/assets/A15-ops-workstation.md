# A15: Ops Engineer Workstation

**Zone:** Front Office (per participant)
**Type:** Linux workstation — SCADA operations engineer's daily driver

## Purpose

This is Sergei Ivanov's workstation. He is the SCADA operations engineer responsible for the NV-3200 generator and the Modbus PLCs that run the plant. His job puts him in front of the HMI several times a week for diagnostic checks and routine maintenance, so he has cached `svc-scada` credentials on this box and a personal sudo rule that lets him re-run a diagnostic script against production without calling the on-call engineer. The diagnostic script does not sanitise its arguments.

A15 is the **only** Front Office asset multi-homed onto the SCADA VLAN. Previously A3 (the corporate wiki) carried this role via an extra network interface — topologically absurd for a public-facing Flask wiki. A15 replaces it with a narratively defensible pivot: an engineer whose day-to-day work legitimately requires OT reach.

**A15 is the gate for flags 18 and 19.** Flag 19 is the splice trigger for the participant's Bunker chain, which makes A15 the upstream gate for the entire Mission 4 (Lights Out) arc. Losing any step in the A15 compromise chain blocks the rest of the scenario — the path has to be earned.

## Configuration

- Base: `debian:bookworm-slim`
- Services:
  - `22/tcp` — OpenSSH (password auth for `s.ivanov`; root login disabled)
  - `80/tcp` — Flask "Ops Telemetry" dashboard (read-only snapshot, no auth, no vulnerability — narrative cover for the box existing)
- Networks:
  - `corporate` — 172.20.10.50
  - `scada` — 172.20.40.20
- **NOT** on `lab`, `bunker-ot`, or any other segment
- `pymodbus` preinstalled (no outbound egress in the range, and Ivanov legitimately uses it)

## User Accounts

| Username | Password | Shell | Notes |
|---|---|---|---|
| `s.ivanov` | `Welcome1` | `/bin/bash` | SCADA ops engineer. Picked the corporate default password during a post-leave reset and never rotated — consistent with the A3 intranet wiki's "several employees still use the default" note that powers flag 9 / flag 10 discovery. |
| `root` | — | `/bin/bash` | No direct SSH login. Privilege escalation via the sudo rule below is the only path in. |

## Attack Chain

The A15 chain is the Expert-tier gate for the SCADA → Bunker arc. Each step must be independently earned.

1. **Discover Ivanov's existence (OSINT).** Breadcrumbs placed on:
   - A0 `/leadership` — Ivanov listed as "Operations Engineer — Plant Systems", reports to Webb
   - A0 `/contact` — email `s.ivanov@boreas-systems.ctf`
   - A4 HR share `org_chart_current.xlsx` — Ivanov row added under Engineering with the note "Operations — generator and plant systems"
2. **Discover his password.** Two reinforcing paths, both consistent with the existing cred patterns:
   - A1 mail thread in Ivanov's inbox: HR welcome-back reset confirmation that quotes `Welcome1` as the corporate default and asks him to rotate on first login (he never did)
   - A3 intranet HR wiki already tells participants `Welcome1` is the default and that several accounts still use it (existing content, flag 9 chain)
   - Either path + a username derived from OSINT yields the SSH cred
3. **SSH foothold.** `ssh s.ivanov@ops-eng01.boreas.local` drops into `/home/s.ivanov`. Home contains:
   - `ops_runbook.pdf` — flavor; startup/shutdown checklist for the NV-3200
   - `.bash_history` — shows `sudo /opt/ops/scada_diag.sh --host scada-gw.boreas.local` as the most-used command, priming the privesc path
   - `notes.txt` — brief aside: *"hmi creds on root's side, ask Dariusz if I forget again"*
4. **Privilege escalation via sudo arg injection.** `sudo -l` reveals exactly one rule:
   ```
   s.ivanov ALL=(root) NOPASSWD: /opt/ops/scada_diag.sh
   ```
   `/opt/ops/scada_diag.sh` is a short bash wrapper that takes `--host <hostname>` and pipes it into `curl` without quoting. A standard injection payload (`--host "x; cat /root/.scada/hmi.json"` or backticks) runs the injected command as root. OWASP CWE-78.
5. **Loot.** `/root/.scada/hmi.json` (mode 600, owned by root) contains:
   - `svc-scada / Sc@da#2025!` — the single-source location for the SCADA HMI credential (A4's `service_account_vault.pdf` loses its `svc-scada` row as part of this change so the cred flows exclusively through A15)
   - `FLAG{5c3e7a9f1b8d4602}` — flag 37
6. **Pivot.** From the A15 shell the participant now has direct network reach to `scada-gw.boreas.local:8080` (HMI) and `:502` (Modbus). `pymodbus` is preinstalled for the flag 19 write sequence. A15 has no internet egress — any `pip install` will fail by design.

## Interfaces

### Flask "Ops Telemetry" dashboard (corporate face, 80/tcp, no auth)

A Jinja-rendered page at `/` showing the last 24 h of generator telemetry (fuel %, coolant temp, thermal safety status) as a static snapshot. Purpose: narrative cover — a plausible reason for A15 to be visible from the corporate network at all. Secondary purpose: a breadcrumb that this box has a live relationship with `scada-gw`.

**No vulnerabilities in the dashboard itself.** The compromise path is SSH + sudo privesc, not the web app. Avoiding a second vuln here keeps A15's attack surface single-purpose and prevents accidental exploit overlap with A3.

### SSH (corporate face, 22/tcp)

Standard OpenSSH. Password auth enabled for `s.ivanov`. Root login disabled. No key auth (deliberate — forces the cred-discovery path).

## Vulnerabilities

- **Credential reuse / default password:** `s.ivanov / Welcome1`. Same well-documented corporate default used elsewhere in the range.
- **Sudo rule + command injection:** `/opt/ops/scada_diag.sh` runs as root and interpolates `--host` verbatim into a curl command. Arbitrary root code execution via shell metacharacters.
- **Plaintext credentials on disk:** root keeps `svc-scada` in an unencrypted JSON file.

## Flags

### Flag 37 — On Call

- **Difficulty:** Hard (200 pts)
- **Location:** `/root/.scada/hmi.json` on A15, readable only as root via the sudo-arg-injection chain above.
- **Flag:** `FLAG{5c3e7a9f1b8d4602}`
- **Mission:** Mission 4 — Lights Out

Flag 37 is a **prerequisite** for flags 18 and 19 — without root on A15 the participant has no route onto the SCADA VLAN, no `svc-scada` credential, and therefore no way to complete the Modbus bypass that trips the local splice trigger.

---

## Build Plan

**Base image:** `debian:bookworm-slim`

**Content directory:** `scenario-dev/polaris/build/A15-ops-workstation/`

### Steps

1. **Install runtime packages**
   - `openssh-server`, `sudo`, `python3`, `python3-flask`, `python3-pymodbus`, `curl`, `coreutils`
2. **Create user account**
   - `useradd -m -s /bin/bash s.ivanov`
   - `echo "s.ivanov:Welcome1" | chpasswd`
3. **Populate `~s.ivanov`**
   - `ops_runbook.pdf` — flavor PDF generated by reportlab
   - `.bash_history` priming the sudo call
   - `notes.txt` with the "hmi creds on root's side" aside
4. **Install the sudo rule**
   - `/etc/sudoers.d/s_ivanov`:
     ```
     s.ivanov ALL=(root) NOPASSWD: /opt/ops/scada_diag.sh
     ```
5. **Install the vulnerable diagnostic script**
   - `/opt/ops/scada_diag.sh` (mode 755, owned by root):
     ```bash
     #!/bin/bash
     HOST=""
     while [[ $# -gt 0 ]]; do
       case "$1" in
         --host) HOST="$2"; shift 2 ;;
         *) shift ;;
       esac
     done
     curl -sS http://$HOST:8080/ping   # UNQUOTED — intentional injection sink
     ```
6. **Plant the loot**
   - `/root/.scada/hmi.json` (mode 600, owned by root):
     ```json
     {
       "target": "scada-gw.boreas.local",
       "username": "svc-scada",
       "password": "Sc@da#2025!",
       "flag": "FLAG{5c3e7a9f1b8d4602}"
     }
     ```
7. **Build the Flask Ops Telemetry dashboard**
   - `/opt/ops/dashboard.py` — single-file Flask app rendering a static snapshot template on 0.0.0.0:80
8. **Configure sshd**
   - `PermitRootLogin no`
   - `PasswordAuthentication yes`
9. **Write Dockerfile + entrypoint**
   - Entrypoint runs sshd in foreground alongside the Flask dashboard (supervisor or a minimal bash launcher)

### Smoketest targets

- From `a14-kali` on corporate: TCP 22 and TCP 80 reachable ✓
- `ssh s.ivanov@ops-eng01.boreas.local` authenticates with `Welcome1` ✓
- `sudo -l` shows the single `scada_diag.sh` rule ✓
- `sudo /opt/ops/scada_diag.sh --host 'x; id'` runs `id` as root ✓
- `/root/.scada/hmi.json` exists with the hmi creds and flag 37 ✓
- From A15: Modbus `connect()` to `scada-gw.boreas.local:502` succeeds ✓
- **Isolation:** A15 cannot reach any `lab` or `bunker-ot` host — 172.20.30.10:22, 172.20.50.5:22, 172.20.50.10:502 all unreachable ✓

## Cross-Asset Impact

Introducing A15 requires the following design-contract changes elsewhere:

- **`A3-web-app.md`** — strip `scada` from A3's network list. A3 is a corporate-only intranet wiki again.
- **`A4-file-share.md` + `A4-file-share/build_documents.py`** — remove the `svc-scada` row from `service_account_vault.pdf` (single-source the cred through A15), add Ivanov row to `org_chart_current.xlsx`.
- **`A5-scada-generator.md`** — update the flag 18 / flag 19 "Reaching it requires" clause: compromise A15 first, then pivot.
- **`A1-mail-server.md`** — seed Ivanov's inbox with the HR welcome-back reset thread.
- **`A0-boreas-website.md`** — add Ivanov to `/leadership` and `/contact`.
- **`architecture.md`** — add A15 to the asset map with the `corporate + scada` edge; add Flag 37 to the flag breakdown and Front Office totals.
- **`shared-constants.md`** — add Ivanov + `Welcome1` to the employee cred quick-ref.

All downstream walkthroughs and smoketests that currently assume A3 is the SCADA pivot host need to be rewritten to route through A15 instead. Walkthrough work is out of scope for the design pass and deferred to the implementation phase.
