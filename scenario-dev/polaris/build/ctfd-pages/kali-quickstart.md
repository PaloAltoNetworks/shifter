---
title: Starting Environment Quickstart
route: kali-quickstart
format: markdown
hidden: false
draft: false
auth_required: true
---

# Starting Environment Quickstart

This page is for operators who want the shortest path from "my range is up" to "I'm solving flags."

## Mission Reference

Mission briefs, objectives, and the target map live on CTFd — in these pages and in the challenge descriptions themselves. The Kali box is for doing the work, not for reading docs. Submission is always on CTFd in your laptop browser; the Kali box has no route to it.

A Modbus helper is on the box when you need it: `/home/kali/tools/modbus_scan.py`.

## Available Immediately

```text
http://boreas-systems.ctf
http://intranet.boreas.local
http://mail.boreas.local
fileserv.boreas.local
http://board.boreas.local
http://git-public.boreas.local
http://pressdrop.boreas.local
http://casefiles.boreas.local
http://dispatch.boreas.local
http://approvals.boreas.local
http://twin-hmi.boreas.local:8080
twin-plc.boreas.local
```

The Lab, Lights Out, and Bunker do **not** start as immediate targets. Those require pivots that you earn through the Front Office.

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

## If You Get Stuck

- Buy the first hint before you start guessing wildly.
- Prefer the objective description and the first hint over jumping straight to broad scans.
- Keep notes on usernames, hostnames, file paths, and recovered credentials. Polaris chains matter.
