---
title: Start Here
route: index
format: markdown
hidden: false
draft: false
auth_required: true
---

# Operation NORTHSTORM

You start on a Kali box. Some missions are reachable immediately. Others only open after you earn the right pivot.

## First Moves

1. Solve **Mission 0 — Kali Warm-Up** for a quick first submit and starter points.
2. Read the [Kali Quickstart](/kali-quickstart) page for hostnames, tools, and copy-paste commands.
3. Start **Mission 1 — Boreas** on the public site, then push into **Mission 2 — Inside Boreas** from the same Kali box.

## What You Can Start Directly From Kali

### Mission 1 — Boreas

Public-facing recon on the Boreas website and DNS:

- company details
- people and org chart
- tech stack
- old site content
- DNS records

### Mission 2 — Inside Boreas

Early Front Office work also starts from Kali:

- intranet
- mail
- file share
- Active Directory lookups once you have credentials

### Later Pivots

- **Mission 3 — The Lab** opens through the research-analyst path.
- **Mission 4 — Lights Out** opens through the ops-engineer path.
- **Mission 5 — Bunker** only matters after the blackout path succeeds in your range.

## Useful Starting Commands

```bash
curl http://boreas-systems.ctf/
dig axfr boreas-systems.ctf @172.20.0.2
curl http://intranet.boreas.local/
smbclient -N //fileserv.boreas.local/Public -c 'ls'
```

## Need a Nudge?

- Challenge hints are available if you get stuck.
- Early hints tell you **where** to look.
- Later hints tell you **what method or tool** matters.
- If a mission says it starts from Kali, do not overcomplicate it with pivots first.

## Read Next

- [Kali Quickstart](/kali-quickstart)
