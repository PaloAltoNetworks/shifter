---
title: Start Here
route: index
format: markdown
hidden: false
draft: false
auth_required: true
---

# Operation NORTHSTORM

When your range starts, some missions are available immediately in your starting environment. Others only open after you earn the right pivot.

## First Moves

1. Solve **Start Here — Kali Warm-Up** for a quick first submit and starter points.
2. Read the [Kali Quickstart](/kali-quickstart) page for hostnames, tools, and copy-paste commands.
3. Choose a lane: start the main campaign with **Mission 1 — Boreas** or start one of the standalone practice missions that are available immediately.

## Available Immediately

### Mission 1 — Boreas

Public-facing recon on the Boreas website and DNS:

- company details
- people and org chart
- tech stack
- old site content
- DNS records

### Mission 2 — Inside Boreas

Early Front Office work also starts in your initial environment:

- intranet
- mail
- file share
- Active Directory lookups once you have credentials

### Missions 6-9 — Standalone Practice Lanes

These are visible immediately and do not depend on the main campaign:

- **Mission 6 — Exposure**: board portal, DOCX internals, git history, leak portal
- **Mission 7 — Counterintel**: badge logs, XML mail rules, browser history, report form
- **Mission 8 — Delivery Denied**: logistics JSON, approval binary, emergency hold workflow
- **Mission 9 — Safety Case**: training HMI, Modbus readback, safe-mode sequence, shutdown

### Requires a Pivot

- **Mission 3 — The Lab** opens through the research-analyst path.
- **Mission 4 — Lights Out** opens through the ops-engineer path.
- **Mission 5 — Bunker** only matters after the blackout path succeeds in your range.

## Useful Starting Commands

```bash
curl http://boreas-systems.ctf/
dig axfr boreas-systems.ctf @172.20.0.2
curl http://intranet.boreas.local/
smbclient -N //fileserv.boreas.local/Public -c 'ls'
curl http://board.boreas.local/
curl http://casefiles.boreas.local/
curl http://dispatch.boreas.local/
curl http://twin-hmi.boreas.local:8080/
```

## Need a Nudge?

- Challenge hints are available if you get stuck.
- Early hints tell you **where** to look.
- Later hints tell you **what method or tool** matters.
- If a mission is marked available immediately, do not overcomplicate it with pivots first.

## Read Next

- [Kali Quickstart](/kali-quickstart)
