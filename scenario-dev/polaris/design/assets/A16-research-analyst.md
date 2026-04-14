# A16: Research Data Analyst Workstation

**Zone:** Front Office (per participant)
**Type:** Linux workstation — senior research data analyst's daily driver

## Purpose

This is Priya Shah's workstation. She is a senior research data analyst who produces executive reports by pulling metrics out of the research database (A8) and report-generation artifacts from the engineering workstation (A6). Her role legitimately requires corporate ↔ lab reachback: she runs psql against A8's unclassified compartments and SSHes into a narrowly-scoped read-only account on A6 to pull generated artifacts. She keeps her credentials in the usual place every tired-of-typing-passwords data analyst keeps them — on disk, in her home directory, unencrypted.

A16 is the **only** Front Office asset multi-homed onto the Lab VLAN. Previously A3 (the corporate wiki) carried this role via an extra network interface, which is topologically absurd — a public-facing Flask wiki has no business sitting on VLAN 30 with the research database. A16 replaces it with a defensible narrative: an analyst whose day-to-day work requires narrow, specific Lab reachback.

A16 is the **on-ramp** for Mission 3 (The Lab). It is deliberately **not** itself a flag box — compromising it is infrastructure work that opens the pivot path, not a trophy. Flag rewards live downstream on A6 / A7 / A8, and the cloned A7 material also feeds the later Bunker phase.

## Configuration

- Base: `debian:bookworm-slim`
- Services:
  - `22/tcp` — OpenSSH (password auth for `p.shah`; root login disabled)
  - `8080/tcp` — Flask "Research Dashboard" (read-only summary of publicly published research metrics, no auth, no vulnerability — narrative cover)
- Networks:
  - `corporate` — 172.20.10.60
  - `lab` — 172.20.30.60
- **NOT** on `scada` or `bunker-ot`
- `postgresql-client` preinstalled (Shah uses psql daily)
- `openssh-client` preinstalled (Shah uses ssh to A6 daily)

## User Accounts

| Username | Password | Shell | Notes |
|---|---|---|---|
| `p.shah` | `Welcome1` | `/bin/bash` | Senior research data analyst. Same corporate-default-password pattern as `s.ivanov`, `m.webb`, and the others listed on the A3 intranet HR wiki. Discoverable via A4 HR org chart + username guessing. |
| `root` | — | `/bin/bash` | No direct SSH login. Not needed for the pivot — Shah's user-owned files already hold the lab creds. |

## Lab Credentials Cached in ~/p.shah

These are the pivot primitives. They are the whole point of compromising A16.

- `~/.pgpass` (mode 600):
  ```
  researchdb.boreas.local:5432:*:lab_general:LabGen2025!
  ```
- `~/.ssh/id_rsa` — **passphrase-less** RSA key, authorised on A6 for a new read-only user `research-analyst@eng-ws01.boreas.local`
- `~/.ssh/id_rsa.pub` — matching public half
- `~/.ssh/config`:
  ```
  Host eng-ws01
      HostName eng-ws01.boreas.local
      User research-analyst
      IdentityFile ~/.ssh/id_rsa
  ```
- `~/reports/daily_integration_report.py` — short Python report script that imports `psycopg2`, connects to `researchdb.boreas.local` using `.pgpass`, SSHes to A6 via the config alias, and rsync-pulls report artifacts. Serves as in-context documentation of how the creds are meant to be used.

## Attack Chain

Deliberately **simpler** than the A15 privilege-escalation chain, because A16's compromise only opens the Lab network — not the A5-driven splice trigger. The friction is in cred discovery, not in local privesc.

1. **Discover Shah's existence.** Breadcrumbs placed on:
   - A4 HR share `org_chart_current.xlsx` — new row "Priya Shah, Senior Research Data Analyst, Research Ops, reports to Vasik"
   - A4 HR share also mentions Shah once in `chen_james_termination.pdf` (HR case notes) as "data analyst who flagged the anomalous access pattern" — tying her into existing HR flavor
   - A0 deliberately does **not** list her (keeps the OSINT surface from overloading; participants have to earn HR access via the flag 9 path first)
2. **Discover her password.** Same `Welcome1` corporate-default pattern. Participants who worked flag 9 already know from the A3 wiki that several accounts still use it. Trying `Welcome1` against a newly-discovered HR-listed username is a natural move.
3. **SSH foothold.** `ssh p.shah@analyst01.boreas.local` drops the participant into `/home/p.shah`.
4. **Harvest lab credentials.** No privesc needed — the creds live in user-owned files:
   - `cat ~/.pgpass` → `lab_general / LabGen2025!`
   - `cat ~/.ssh/config` and `ls -la ~/.ssh/` → the `research-analyst@eng-ws01` SSH alias + passphrase-less private key
   - `cat ~/reports/daily_integration_report.py` → context for how the creds connect
5. **Pivot into Lab.** From A16 directly (A16 is already on VLAN 30):
   - `psql -h researchdb.boreas.local -U lab_general -d postgres` → opens compartment_a and compartment_c (public) access. Unlocks flag 21 directly and provides the pivot surface for flag 27's SQLi and flag 28's compartment_c walk (the latter still requires independently discovered `lab_mfg` creds — A16 does not shortcut that step).
   - `ssh -F ~/.ssh/config eng-ws01` → drops the participant into `research-analyst@eng-ws01.boreas.local` (A6) as a narrowly-scoped read-only user (see "A6 downstream changes" below).

## What A16 Compromise Actually Unlocks

A16's goal is to **unblock** the Lab mission arc without trivialising it. The `research-analyst` account on A6 is deliberately narrow:

| Lab flag | A16 / research-analyst can solve? | Still requires |
|---|---|---|
| 20 — Default creds on dev tooling (`jenkins`) | **No** — research-analyst cannot read `~jenkins/.credentials` | Separate jenkins SSH cred (currently `build2025`) |
| 21 — compartment_a structural specs | **Yes** — directly via A16 `.pgpass` + lab_general | — |
| 22 — `/opt/builds/latest/reactor_interface_spec.txt` | **Yes** — research-analyst can read `/opt/builds/` | — |
| 23 — `standard/stress_test_44.dat` | **Yes** — research-analyst can read `standard/` (mode 755 per A6 design) | — |
| 24 — Gitea navigation-controller deploy.yml history | **Yes** — A7 is lab-only and A16 is the intended pivot path into it | Gitea credential discovery still required |
| 25 — `midnight/` restricted dir | **No** — mode 700 owned by r.tanaka | tanaka creds or A6 privesc |
| 26 — nielsen's `designs/` | **No** — mode 700 owned by p.nielsen | nielsen creds or A6 privesc |
| 27 — SQLi into compartment_b | **Yes** — SQLi runs over lab_general's own search function | — |
| 28 — compartment_c FINAL ASSEMBLY JSONB | **Partial** — research-analyst cannot read the `.pgpass` file on A6 that has lab_mfg; participant must still find `lab_mfg / Mfg2025!` via the nielsen chain | nielsen creds → A6 `.pgpass` OR other lab_mfg source |
| 29 — leviathan-assembly schematic git history | **Yes** — A7 is lab-only and A16 is the intended pivot path into it | Gitea credential discovery still required |
| 30 — GPG chain (`/tmp/.deleted/*.gpg`) | **Yes** — research-analyst can read `/tmp/.deleted/` | GPG private key still on A8, passphrase still on A7 — those steps are unchanged |

Result: A16 unlocks **5 flags immediately** (21, 22, 23, 27, 30's A6 half) and **leaves 6 flags requiring further in-Lab credential work** (20, 24, 25, 26, 28, 29). That's a sensible difficulty gradient — A16 is the gate, not the whole arc.

## Vulnerabilities

- **Credential reuse / default password:** `p.shah / Welcome1`, the same corporate default pattern.
- **Plaintext credentials on disk:** `.pgpass` and the SSH private key are both unencrypted in her home directory.
- **Passphrase-less SSH key:** convenience over hygiene; anyone who can read `~/.ssh/id_rsa` can immediately use it.

No web vuln on the Flask Research Dashboard (intentional — keeps A16's attack surface single-purpose and matches A15's "narrative cover only" dashboard pattern).

## Flags

### Flag 38 — The Analyst's Desk

- **Difficulty:** Medium (100 pts)
- **Location:** `~p.shah/.reports/ANALYST_TOKEN` on A16 — a world-readable file in the report-generation directory that the daily report script uses as an auth token for a stub reporting API. The file contains `FLAG{8b2d4f1a0c5e7396}`. Once the participant is logged in as `p.shah` (step 3 of the Attack Chain) the file is immediately readable — no privesc, no further chaining. This is the "reward for the compromise" flag; the pivot creds in the same home directory are then used against A6 / A8 for the downstream Lab flags.
- **Flag:** `FLAG{8b2d4f1a0c5e7396}`
- **Mission:** Mission 3 — The Lab

Flag 38 is deliberately a **Medium-tier reward**, not an Expert gate. The A16 compromise is infrastructure work that opens the Lab pivot, and flag 38 is the participant's pay-off for completing it. Unlike flag 37 (the Expert A15 privesc), earning flag 38 requires only cred discovery + SSH — no privilege escalation, no command injection. That hardness level matches what the participant then has to do downstream: most of the unlocked Lab flags are themselves Medium-tier, so the gate difficulty should not exceed the reward it opens.

---

## Build Plan

**Base image:** `debian:bookworm-slim`

**Content directory:** `scenario-dev/polaris/build/A16-research-analyst/`

### Steps

1. **Install runtime packages**
   - `openssh-server`, `openssh-client`, `postgresql-client`, `python3`, `python3-flask`, `python3-psycopg2`, `coreutils`
2. **Create user account**
   - `useradd -m -s /bin/bash p.shah`
   - `echo "p.shah:Welcome1" | chpasswd`
3. **Generate passphrase-less SSH keypair at build time**
   - `ssh-keygen -t rsa -b 2048 -N "" -f /tmp/a16-research-analyst-key`
   - Public half goes into A16's `build/_shared/research-analyst-key/research-analyst.pub` for A6 to COPY during its image build
   - Private half is placed in `/home/p.shah/.ssh/id_rsa` on A16
4. **Populate `~p.shah`**
   - `.pgpass` (mode 600): `researchdb.boreas.local:5432:*:lab_general:LabGen2025!`
   - `.ssh/config` with the `eng-ws01` alias
   - `reports/daily_integration_report.py` — a short realistic report script using psycopg2 + subprocess ssh
   - `.reports/ANALYST_TOKEN` — one-line file containing `FLAG{8b2d4f1a0c5e7396}` (flag 38). The file is referenced by `daily_integration_report.py` as an auth header value for a stub reporting API, so its presence and purpose are self-explanatory to a participant reading the code.
5. **Build the Flask Research Dashboard (narrative cover)**
   - `/opt/research/dashboard.py` — single-file Flask app on 0.0.0.0:8080 rendering a static JSON snapshot. No auth, no vulns.
6. **Configure sshd**
   - `PermitRootLogin no`
   - `PasswordAuthentication yes`
7. **Write Dockerfile + entrypoint**
   - Entrypoint runs sshd + dashboard

### Smoketest targets

- From `a14-kali` on corporate: TCP 22 and TCP 8080 reachable ✓
- `ssh p.shah@analyst01.boreas.local` authenticates with `Welcome1` ✓
- `~p.shah/.pgpass` and `~p.shah/.ssh/id_rsa` exist with correct modes ✓
- From A16: `psql -h researchdb.boreas.local -U lab_general -d postgres -c "SELECT 1"` succeeds ✓
- From A16: `ssh -i ~p.shah/.ssh/id_rsa research-analyst@eng-ws01.boreas.local whoami` returns `research-analyst` ✓
- **Isolation:** A16 cannot reach `scada` or `bunker-ot` — 172.20.40.10:502, 172.20.50.5:22, 172.20.50.10:502 all unreachable ✓

## Downstream Design Impact

Introducing A16 requires the following design-contract changes:

- **`A3-web-app.md`** — strip `lab` from A3's network list. Combined with the A15 change, A3 returns to `corporate` only.
- **`A6-engineering-workstation.md`** — add a new `research-analyst` user with the following properties:
  - Shell `/bin/bash`, home `/home/research-analyst`, no password (key-only auth)
  - `authorized_keys` contains the public half of the A16-generated keypair (pulled from `build/_shared/research-analyst-key/research-analyst.pub`)
  - Group membership: can read `/opt/builds/` (already world-readable), `/home/r.tanaka/simulations/standard/` (already mode 755), `/tmp/.deleted/` (needs to be world-readable or research-analyst added to whichever group owns it)
  - **Cannot** read `/home/r.tanaka/simulations/midnight/` (mode 700), `/home/p.nielsen/designs/` (mode 700), or `/home/jenkins/.credentials` (mode 600)
  - No sudo rights. No ability to write anywhere under `/home/r.tanaka`, `/home/p.nielsen`, or `/opt/builds`.
- **`A4-file-share.md` + `A4-file-share/build_documents.py`** — add Shah row to `org_chart_current.xlsx`, reference her in `chen_james_termination.pdf` HR case notes as the flagging analyst.
- **`architecture.md`** — add A16 to the asset map with the `corporate + lab` edge.
- **`shared-constants.md`** — add Shah + `Welcome1` to the employee cred quick-ref.

Walkthrough work (rewriting `flags-20-30-lab.md` to route through A16) is out of scope for the design pass and happens during implementation.
