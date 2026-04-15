---
title: Starting Environment Quickstart
route: kali-quickstart
format: markdown
hidden: false
draft: false
auth_required: true
---

# Starting Environment Quickstart

This page is for participants who want the shortest path from “my range is up” to “I’m solving flags.”

## Local Orientation

These files already exist on the Kali workstation:

- `/home/kali/README.md`
- `/home/kali/mission_brief.txt`
- `/home/kali/tools/flag_submit.sh`
- `/home/kali/tools/modbus_scan.py`

Use them as reference, but do the actual mission work on the Boreas surfaces below.

## Available Immediately

```text
http://boreas-systems.ctf
http://intranet.boreas.local
//fileserv.boreas.local/Public
mail.boreas.local
http://board.boreas.local
http://git-public.boreas.local
http://pressdrop.boreas.local
http://casefiles.boreas.local
http://dispatch.boreas.local
http://approvals.boreas.local
http://twin-hmi.boreas.local:8080
twin-plc.boreas.local:502
```

The Lab, Lights Out, and Bunker do **not** start as immediate targets. Those require pivots later.

## Good First Commands

```bash
curl http://boreas-systems.ctf/
curl http://boreas-systems.ctf/about.html
dig axfr boreas-systems.ctf @172.20.0.2
curl http://intranet.boreas.local/
smbclient -N //fileserv.boreas.local/Public -c 'ls'
curl http://board.boreas.local/
curl http://casefiles.boreas.local/
curl http://dispatch.boreas.local/
curl http://twin-hmi.boreas.local:8080/
```

## Good First Tools

- `curl`
- `dig`
- `smbclient`
- `pdfinfo`
- `pdf2txt.py`
- `git`
- `sqlite3`
- `strings`
- `python3`

## Once You Have Credentials

These become relevant only after you recover usernames and passwords and earn the right pivot:

```bash
ssh analyst01.boreas.local
ssh ops-eng01.boreas.local
```

Those pivots lead into:

- **Mission 3 — The Lab**
- **Mission 4 — Lights Out**

## If You Get Stuck

- Buy the first hint before you start guessing wildly.
- Prefer the challenge description and the first hint over jumping straight to broad scans.
- Keep notes on usernames, hostnames, file paths, and recovered credentials. Polaris chains matter.
