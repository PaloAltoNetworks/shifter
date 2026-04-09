# A3: Web App / Intranet

**Zone:** Front Office (per participant)
**Type:** Web application (Django, Flask, or similar)

## Purpose

Boreas Systems internal intranet and wiki. This is the first thing most participants will attack after the OSINT phase — it's web-facing within the Front Office network, has common web vulnerabilities, and contains internal documentation that references "the project" in ways that don't add up for a consultancy.

## Configuration

- Web application on port 80/443
- Login page with employee authentication (ties to AD on A2 or local accounts)
- Wiki/CMS with internal documentation pages
- Admin panel with default or weak credentials
- Deliberately vulnerable: SQLi, directory traversal, or exposed config files

## Content

### Public (pre-auth) Pages
- Login page
- "Forgot password" page (leaks valid usernames via error messages)
- A maintenance page at /status that shows server info

### Authenticated Pages
- **Company Wiki** — internal documentation, project pages, HR policies
- **Procurement Portal** — links to the file share for POs and invoices
- **IT Knowledge Base** — setup guides that reference internal hostnames and network architecture
- **"The Project" page** — a wiki page titled "Project Coordination" that is suspiciously vague. References "Phase 3 integration" and "site preparation for primary power source delivery" without ever naming what the project is. Links to the Lab network "for authorized personnel."

### Admin Panel
- Accessible at /admin or /wiki/admin
- Default credentials: `admin` / `admin` or discoverable from config file
- Admin panel shows all wiki pages including draft/unpublished ones
- One draft page is titled "LEVIATHAN Assembly Schedule" but the body just says "[MOVED TO SECURE SYSTEM]"

## Vulnerabilities

- Config file exposed at /.env or /config.bak containing database credentials and a comment with the admin password
- SQL injection in the search function (allows dumping user table)
- Directory traversal in a file download feature (can read /etc/passwd, local config files)

## Flags

### Flag 7 — Creds in web app config
- **Difficulty:** Easy
- **Location:** Accessible at `/.env` or `/config.bak`. The file contains database credentials, the admin password, and the flag as a commented "API key."
- **Flag:** `FLAG{4f2e8b7a1c6d9035}`
- **Mission:** M1

### Flag 12 — Internal wiki — "the project" references
- **Difficulty:** Easy
- **Location:** After logging in (using creds from the config file or from A0 employee info + weak passwords), navigate the wiki. The "Project Coordination" page has the flag embedded in an HTML comment in the page source.
- **Flag:** `FLAG{d8a3c5e9f1b07264}`
- **Mission:** M1, M2
