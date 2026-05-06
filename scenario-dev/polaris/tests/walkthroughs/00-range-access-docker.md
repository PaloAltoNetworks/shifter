# Range Access — Docker Compose Environment

Everything runs as containers on `ctf-range-builder` (10.100.0.5) in GCP project `prod-rwctxzl6shxk`, zone `us-east4-a`.

## How to Connect

All commands in the walkthroughs run from the participant perspective: a shell on the Kali attack workstation (A14) sitting on the shared + corporate networks.

## Network Topology

The Kali container is on two networks: `shared` (172.20.0.x) and `corporate` (172.20.10.x).

### What Kali CAN reach directly

| Service | Hostname | IP | Port | Notes |
|---------|----------|-----|------|-------|
| A0 Website | boreas-systems.ctf | 172.20.0.10 | 80 | `curl http://172.20.0.10/` |
| DNS | — | 172.20.0.2 | 53 | `dig axfr boreas-systems.ctf @172.20.0.2` |
| A1 Mail | mail.boreas.local | 172.20.10.20 | 25,143,80 | SMTP, IMAP, Roundcube |
| A3 Intranet | intranet.boreas.local | 172.20.10.30 | 80 | `curl http://172.20.10.30/` |
| A4 File Share | fileserv.boreas.local | 172.20.10.40 | 445 | `smbclient //172.20.10.40/Public` |
| A15 Ops Eng | ops-eng01.boreas.local | 172.20.10.50 | 22, 80 | Pivot host for SCADA (flag 37 gate) |
| A16 Research Analyst | analyst01.boreas.local | 172.20.10.60 | 22, 8080 | Pivot host for Lab + Gitea (flag 38) |
| A2 Windows DC | dc01.boreas.local | 10.1.100.11 | 53, 88, 135, 389, 445, 464, 636, 3268, 3269, 49152-65535 | Windows Server 2022 AD DC in the range VPC (adjacent to the docker host) — reachable from Kali via `dc01.boreas.local` through the compose DNS forwarder |

### What Kali CANNOT reach (requires pivot)

| Service | IP | Network | How to reach |
|---------|-----|---------|-------------|
| A5 SCADA HMI | 172.20.40.10 | scada (VLAN 40) | Pivot through **A15** (the ops engineer workstation) after flag 37 |
| A6 Workstation | 172.20.30.10 | lab (VLAN 30) | Pivot through **A16** (the research analyst workstation) after flag 38 |
| A7 Gitea | 172.20.30.20 | lab (VLAN 30) | Pivot through **A16**; has `git` preinstalled |
| A8 Database | 172.20.30.30 | lab (VLAN 30) | Pivot through **A16** via cached `.pgpass` |
| A9 Splice | 172.20.60.5 | splice-link | Pre-wired link to Kali (`splice-relay`, SSH `root / splice2025`) — represents the post-meltdown local splice install |
| A10 Tail | 172.20.50.10 | bunker-ot | Via A9 after gate |
| A11 Leg | 172.20.50.11 | bunker-ot | Via A9 after gate |
| A12 Arms | 172.20.50.12 | bunker-ot | Via A9 after gate |
| A13 Brain | 172.20.50.50 | bunker-ot | Via A9 after gate |

### DNS Resolution

The Kali container uses 172.20.0.2 as its DNS server. Hostnames like `boreas-systems.ctf` and `mail.boreas.local` should resolve. If not, use IPs directly.

## Credentials Quick Reference

| Account | Password | Where |
|---------|----------|-------|
| d.kowalski | P@ssw0rd123 | A3 intranet, A1 webmail, A2 SMB |
| admin | admin | A3 admin panel |
| m.webb | Welcome1 | A4 HR + Procurement shares (Executive), A3 intranet |
| s.ivanov | Welcome1 | A15 Ops workstation SSH (flag 37) |
| p.shah | Welcome1 | A16 Research analyst workstation SSH (flag 38) |
| svc-scada | Sc@da#2025! | A5 SCADA control panel — cached in `/root/.scada/hmi.json` on A15, reachable only via flag 37 privesc |
| svc-backup | Password1 | A2 Kerberoast target + DCSync (cracked from krb5tgs) |
| Administrator | (use PTH) | A2 admin_flag share — Administrator's cleartext is random; use `smbclient.py -hashes :<nt>` with the NT hash from `secretsdump.py` |
| jenkins | build2025 | A6 SSH |
| r.tanaka | SimEngine#42 | A6 SSH, A7 Gitea, A8 PostgreSQL |
| p.nielsen | Hydraulics1 | A6 SSH, A7 Gitea, A8 PostgreSQL |
| e_vasik / e.vasik | Reactor#Core9 | A1 webmail, A2 AD, A6 SSH, A7 Gitea (Project-L), A8 PostgreSQL (all compartments) |
| svc-fileshare | F1l3Sh@r3Svc! | A4 IT share (from A1 Kowalski "creds backup" email) |
| lab_general | LabGen2025! | A8 PostgreSQL compartment_a (from A3 /.env leak) |
| lab_mfg | Mfg2025! | A8 PostgreSQL compartment_c (from A6 /home/p.nielsen/.pgpass) |
| root | splice2025 | A9 SSH |

## Managing the Range

From the builder VM (not inside Kali). The range source lives at
`/home/atomik/range/` (mirror of `scenario-dev/polaris/` in the repo),
so the compose file is at `$RANGE_DIR/build/docker-compose.yml` and all
orchestration goes through the scripts in `$RANGE_DIR/tests/`:

```bash
# Full setup: build + up + wait ready
bash /home/atomik/range/tests/setup.sh

# Run the full smoketest sweep (15 asset smoketests + isolation)
bash /home/atomik/range/tests/run-all-smoketests.sh

# Reset sticky-state services (a5/a10/a11/a12/a13) between test runs or
# before handing to a new participant
bash /home/atomik/range/tests/reset.sh

# Raw docker compose commands. Project name defaults to "build" (the
# parent dir of docker-compose.yml) which matches the production
# user_data path and the polaris-splice-watcher's default
# SPLICE_NETWORK=build_splice-link. Always cd into build/ first or pass
# `-f` and let docker derive project=build from the file's parent dir.
cd /home/atomik/range/build
docker compose ps
docker compose down
docker compose build a12-arms
docker compose up -d a12-arms
docker logs a13-brain
```
