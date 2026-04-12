# NORTHSTORM Range — Session Handoff

## What's Done

### Infrastructure (on ctf-range-builder VM, 10.100.0.5)
- 15 Docker containers running via `docker compose` at `/home/atomik/range/`
- Network topology matches architecture design:
  - shared (172.20.0.0/24): A0, A7, DNS, A14
  - corporate (172.20.10.0/24): A1, A3, A4, A14
  - scada (172.20.40.0/24): A5, A3 (pivot)
  - lab (172.20.30.0/24): A6, A7, A8, A3 (pivot)
  - bunker-ot (172.20.50.0/24): A9, A10, A11, A12, A13
- A2 Windows DC is external VM at 10.100.0.4 (may be stopped — start it before testing)
- All services verified working: Gitea (6 repos), PostgreSQL (GPG key embedded), DNS (AXFR), all Modbus controllers, brain, SCADA, web apps

### Content (all built and baked into container images)
- 36 flags verified across multiple test rounds on the flat VM setup
- All Dockerfiles, entrypoints, and build scripts in `docs/ctf/mechag/`
- docker-compose.yml defines the full range

## What's NOT Done

### 1. Walkthrough Docs Need Rewriting
The smoketest walkthroughs in `temp/tests/smoketests/` still have wrong IPs and instructions from the old flat setup. They MUST be rewritten to match the Docker compose topology BEFORE testing.

Files to rewrite:
- `flags-07-19-front-office.md` — Header still references old A5 IP (172.20.10.50). Flags 18/19 need pivot instructions through A3 to reach A5 at 172.20.40.10.
- `flags-20-30-lab.md` — Instructions reference local paths and localhost. Must use container exec or SSH from Lab containers. A7 Gitea is at 172.20.0.70:3000 (shared net, reachable from Kali). A6 at 172.20.30.10 (lab net, NOT reachable from Kali). A8 at 172.20.30.30.
- `flags-31-36-bunker.md` — Bunker controllers are at 172.20.50.x (not 172.20.40.x from old setup). Port 502 (production, not 5020).
- `flags-01-06-osint.md` — Mostly correct, just needs old results stripped.
- `00-range-access-docker.md` — Partially updated but needs final review for all IPs.

### 2. Smoketest Agent Run
After docs are correct, launch 4 agents with ONLY: "Read the doc file and follow it. Log results at the bottom." ZERO hints in the prompt. If anything fails, fix the range or the doc, never the prompt.

### 3. Old Results Must Be Stripped
Every walkthrough file has stale smoketest results appended from previous runs. Strip everything after the last `---` before "Smoketest Results" in each file.

## Key Gotchas Discovered
- Gitea Alpine image needs `python3`, `bash`, `git`, `curl` installed (bootstrap uses python3)
- Gitea must NOT run as root — use `su -s /bin/sh git -c "gitea web ..."`
- Write app.ini BEFORE chowning `/data` to git (otherwise config file is root-owned and Gitea can't modify it)
- `git push` from bare repos needs `git config --global --add safe.directory '*'`
- A3 must be multi-homed on corporate + scada + lab networks (it's the pivot point)
- Docker `nc` may not be installed in slim Python images — use `python3 -c "import socket..."` for connectivity tests
- The `UserPromptSubmit` hook in `.claude/settings.local.json` injects a quality reminder every turn

## How to Access
```bash
# SSH to builder VM
gcloud compute ssh ctf-range-builder --zone=us-east4-a --ssh-key-file=~/.ssh/id_rsa

# Check containers
cd /home/atomik/range && sudo docker compose ps

# Get a Kali shell
sudo docker exec -it a14-kali /bin/bash

# Start the Windows DC (if stopped)
gcloud compute instances start ctf-test-a2-windc --zone=us-east4-a

# Full rebuild after code changes
sudo docker compose down && sudo docker network prune -f && sudo docker compose up -d --build
```
