# Range Access — Read This First

You are testing the NORTHSTORM CTF range. Everything is running on a GCP test VPC. Do NOT read the rest of this repo for context — these instructions tell you everything you need.

## How to Connect

All services run on a single test VM (`ctf-test-attacker`, 10.100.0.3) in GCP project `prod-rwctxzl6shxk`, zone `us-east4-a`. The Windows DC is a separate VM (10.100.0.4).

SSH to the attacker VM:
```
gcloud compute ssh ctf-test-attacker --zone=us-east4-a --ssh-key-file=~/.ssh/id_rsa
```

Once on the VM, activate the Python environment:
```
source ~/impacket-env/bin/activate
```

## Services and Ports

All services run on the attacker VM (127.0.0.1) unless noted. They must be started before testing — they are NOT auto-started.

### Start All Services
```bash
source ~/impacket-env/bin/activate
killall python3 2>/dev/null; sleep 1
python3 /tmp/a10_server.py > /dev/null 2>&1 &    # Tail controller (Modbus)
python3 /tmp/A11-leg-controller_server.py > /dev/null 2>&1 &  # Leg controller
python3 /tmp/A12-arms-controller_server.py > /dev/null 2>&1 &  # Arms controller
python3 /tmp/A13-brain_server.py > /dev/null 2>&1 &  # Brain (TCP 9100)
python3 /tmp/a5_server.py > /dev/null 2>&1 &      # SCADA HMI + Modbus PLC
python3 /tmp/a3_server.py > /dev/null 2>&1 &      # Intranet web app
python3 /tmp/a0_server.py > /dev/null 2>&1 &      # Boreas website
sleep 4
```

Gitea and PostgreSQL are already running (started at boot).

### Service Map

| Service | Address | Port | Notes |
|---------|---------|------|-------|
| A0 Boreas Website | 127.0.0.1 | 8082 | `curl http://127.0.0.1:8082/` |
| A1 Mail Content | N/A | N/A | EML files at `/tmp/a1-content/` (no live mail server) |
| A2 Domain Controller | 10.100.0.4 | 88,389,445 | Separate Windows VM — must `gcloud compute instances start ctf-test-a2-windc --zone=us-east4-a` first, wait ~2 min |
| A3 Intranet | 127.0.0.1 | 8081 | `curl http://127.0.0.1:8081/` |
| A4 File Share Content | N/A | N/A | Files at `/tmp/a4-content/` (no live Samba server) |
| A5 SCADA HMI | 127.0.0.1 | 8080 (web), 5050 (Modbus) | `curl http://127.0.0.1:8080/` |
| A6 Eng Workstation Content | N/A | N/A | Files at `/tmp/a6-content/` (no live SSH server) |
| A7 Gitea | 127.0.0.1 | 3000 | `curl http://127.0.0.1:3000/` |
| A8 PostgreSQL | 127.0.0.1 | 5432 | `sudo -u postgres psql` |
| A9 Splice Landing Content | N/A | N/A | Files at `/tmp/a9-content/` |
| A10 Tail Controller | 127.0.0.1 | 5020 | Modbus/TCP (production: 502) |
| A11 Leg Controller | 127.0.0.1 | 5021 | Modbus/TCP (production: 502) |
| A12 Arms Controller | 127.0.0.1 | 5022 | Modbus/TCP (production: 502) |
| A13 Brain | 127.0.0.1 | 9100 | Custom binary protocol |
| A14 Kali Content | N/A | N/A | Files in repo: `docs/ctf/mechag/A14-kali/` |

### Important Differences from Production

- **Modbus ports are non-standard** (5020/5021/5022 instead of 502) because port 502 requires root. Smoketest instructions say port 502 — substitute the test ports.
- **A1, A4, A6 are content-on-disk**, not live services. To test flags in those assets, read the files directly (e.g., `cat /tmp/a1-content/d.kowalski/01_welcome.eml`). In production these will be real mail/Samba/SSH servers.
- **A2 Windows DC is a separate VM** that costs money when running. Start it, test, stop it.
- **Gitea users have password `TestPass123!`**, not the AD passwords listed in the asset docs.

### Environment Variables for Test Suite

If you want to run the automated test suite:
```bash
export A10_HOST=127.0.0.1 A10_PORT=5020
export A11_HOST=127.0.0.1 A11_PORT=5021
export A12_HOST=127.0.0.1 A12_PORT=5022
export A13_HOST=127.0.0.1 A13_PORT=9100
export A5_HOST=127.0.0.1 A5_WEB_PORT=8080 A5_MODBUS_PORT=5050
export A3_HOST=127.0.0.1 A3_PORT=8081
export A0_HOST=127.0.0.1 A0_PORT=8082
export A2_HOST=10.100.0.4 A2_ADMIN_PASS=CTFAdmin2026!
bash /tmp/tests/run_all.sh
```

### Credentials Quick Reference

| Account | Password | Where to Use |
|---------|----------|-------------|
| gitea_admin | AdminPass123! | Gitea admin API |
| e_vasik | TestPass123! | Gitea (Lab-Access + Project-L repos) |
| r_tanaka | TestPass123! | Gitea (Lab-Access repos) |
| d_kowalski | TestPass123! | Gitea (public repos only) |
| d.kowalski | P@ssw0rd123 | A3 intranet login, A1 webmail |
| admin | admin | A3 intranet admin panel |
| svc-scada | Sc@da#2025! | A5 SCADA control panel |
| svc-backup | Password1 | A2 Kerberoast target, DCSync |
| Administrator | CTFAdmin2026! | A2 Windows DC (domain admin) |
| lab_general | LabGen2025! | A8 PostgreSQL (compartment_a access) |
| lab_mfg | Mfg2025! | A8 PostgreSQL (compartment_c access) |
| vasik | Reactor#Core9 | A8 PostgreSQL (all compartments) |
| jenkins | build2025 | A6 SSH (flag 20) |
| r.tanaka | SimEngine#42 | A6 SSH (MIDNIGHT access) |
| p.nielsen | Hydraulics1 | A6 SSH (designs access) |

## Smoketest Files

After reading this file, proceed to:
1. `flags-01-06-osint.md` — Website flags
2. `flags-07-19-front-office.md` — Intranet, mail, file share, AD, SCADA flags
3. `flags-20-30-lab.md` — Engineering workstation, source repos, database flags
4. `flags-31-36-bunker.md` — Modbus controllers and brain flags

Each file has step-by-step instructions for every flag.
