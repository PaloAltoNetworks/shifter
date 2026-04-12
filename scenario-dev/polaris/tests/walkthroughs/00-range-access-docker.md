# Range Access — Docker Compose Environment

Everything runs as containers on `ctf-range-builder` (10.100.0.5) in GCP project `prod-rwctxzl6shxk`, zone `us-east4-a`.

## How to Connect

SSH to the builder VM:
```
gcloud compute ssh ctf-range-builder --zone=us-east4-a --ssh-key-file=~/.ssh/id_rsa
```

Get a shell inside the Kali container (this is the participant perspective):
```
sudo docker exec -it a14-kali /bin/bash
```

All commands in the smoketest walkthroughs should be run FROM INSIDE the Kali container unless stated otherwise.

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
| A7 Gitea | git.boreas.local | 172.20.0.70 | 3000 | On shared network. `curl http://172.20.0.70:3000/` |
| A2 Windows DC | dc01.boreas.local | 10.100.0.4 | 88,389,445 | External VM, reachable from corporate net |

### What Kali CANNOT reach (requires pivot)

| Service | IP | Network | How to reach |
|---------|-----|---------|-------------|
| A5 SCADA HMI | 172.20.40.10 | scada (VLAN 40) | Pivot through A3 (which is on both corporate and scada nets) |
| A6 Workstation | 172.20.30.10 | lab (VLAN 30) | Pivot through A3 (which is on both corporate and lab nets) |
| A8 Database | 172.20.30.30 | lab (VLAN 30) | Pivot through A3 → A6, or access from A6 directly |
| A9 Splice | 172.20.50.5 | bunker-ot (VLAN 50) | Collective gate must fire first |
| A10 Tail | 172.20.50.10 | bunker-ot | Via A9 after gate |
| A11 Leg | 172.20.50.11 | bunker-ot | Via A9 after gate |
| A12 Arms | 172.20.50.12 | bunker-ot | Via A9 after gate |
| A13 Brain | 172.20.50.50 | bunker-ot | Via A9 after gate |

### DNS Resolution

The Kali container uses 172.20.0.2 as its DNS server. Hostnames like `boreas-systems.ctf` and `mail.boreas.local` should resolve. If not, use IPs directly.

### For testing Lab/Bunker flags without pivot

To test flags in isolated networks during development, you can exec into those containers directly:
```
sudo docker exec -it a6-workstation /bin/bash     # Lab
sudo docker exec -it a9-splice /bin/sh             # Bunker gateway
sudo docker exec -it a8-database psql -U postgres  # Database
```

This bypasses network isolation. In production, participants must pivot.

## Credentials Quick Reference

| Account | Password | Where |
|---------|----------|-------|
| d.kowalski | P@ssw0rd123 | A3 intranet, A1 webmail, A2 SMB |
| admin | admin | A3 admin panel |
| svc-scada | Sc@da#2025! | A5 SCADA control panel |
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

# Raw docker compose commands — always use -p range so network names
# stay stable across layout moves, and point at the compose file under
# build/
docker compose -p range -f /home/atomik/range/build/docker-compose.yml ps
docker compose -p range -f /home/atomik/range/build/docker-compose.yml down
docker compose -p range -f /home/atomik/range/build/docker-compose.yml build a12-arms
docker compose -p range -f /home/atomik/range/build/docker-compose.yml up -d a12-arms
docker logs a13-brain
```
