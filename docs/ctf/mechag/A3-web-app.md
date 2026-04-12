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

---

## Build Plan

**Base image:** python:3.12-slim (Flask app)

**Content directory:** `docs/ctf/mechag/A3-web-app/`

### Steps

1. **Build Flask web application**
   - Login page with username/password form
   - "Forgot password" page that leaks valid usernames via different error messages ("user not found" vs "incorrect password")
   - `/status` page showing server info (Python version, hostname, uptime)
   - Admin panel at `/admin` with default creds `admin`/`admin`

2. **Build wiki/CMS content pages (post-auth)**
   - Company Wiki landing page
   - HR Policies page
   - Procurement Portal page (links to A4 file share paths)
   - IT Knowledge Base — setup guides referencing internal hostnames (mail.boreas.local, dc.boreas.local, scada-gw.boreas.local)
   - "Project Coordination" page — suspiciously vague, references Phase 3 integration, primary power source delivery, link to Lab network
   - Admin-only draft page: "LEVIATHAN Assembly Schedule" with body "[MOVED TO SECURE SYSTEM]"

3. **Create user accounts in app database**
   - Map to same employees as A1/A2 (or accept AD creds if integrating with A2)
   - admin/admin for the admin panel
   - Local SQLite DB for simplicity

4. **Plant the exposed config file**
   - `/.env` or `/config.bak` served as static file
   - Contains: DB credentials, admin password, flag 7 as a commented "API key"
   - Ensure nginx/Flask doesn't block dotfile access

5. **Implement SQL injection vulnerability**
   - Search function with unsanitized query concatenation
   - Must allow dumping the user table (usernames + password hashes)
   - Use SQLite so no external DB dependency

6. **Implement directory traversal vulnerability**
   - File download endpoint like `/download?file=doc.pdf`
   - Path traversal allows reading `/etc/passwd`, local config files
   - Not needed for any flag, but adds realism and alternate attack paths

7. **Embed flags**
   - Flag 7: In the `/.env` config file as `API_KEY=FLAG{...}`
   - Flag 12: HTML comment in the "Project Coordination" wiki page source

8. **Write Dockerfile**
   - Install Flask, gunicorn
   - Copy app code, templates, static files, SQLite DB
   - Entrypoint: start gunicorn on port 80
   - Expose port 80
