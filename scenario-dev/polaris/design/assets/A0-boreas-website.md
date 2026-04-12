# A0: Boreas Systems Corporate Website

**Zone:** Shared (single instance for all participants)
**Type:** Static/semi-static web application

## Purpose

Public-facing corporate website for Boreas Systems, AURORA COLLECTIVE's front company. This is the first thing participants see and the entry point for OSINT reconnaissance. It needs to look like a real, slightly boring technology consultancy website while containing breadcrumbs that feed the narrative.

## Configuration

- Web server (nginx or similar) serving a corporate site
- No authentication required for most content
- Some areas behind basic auth or "employee portal" login (doesn't need to work — it's a red herring that points people toward the real Front Office)
- DNS records configured to be discoverable (MX, TXT, subdomains)

## Content

### Public Pages
- **Homepage** — "Boreas Systems: Advanced Technology Solutions." Generic consulting language. Headquarters listed as a nondescript industrial park address.
- **About Us** — Founded 2018. "Multidisciplinary engineering consultancy specializing in defense and industrial technology." Vague enough to be a cover.
- **Leadership Team** — CEO Viktor Harlan, CTO Dr. Elena Vasik, COO Marcus Webb. Photos (AI-generated or stock). Bios that are plausible but sparse.
- **Careers** — Active job postings that leak the tech stack and hint at what they're really doing.
- **Contact** — Office address, general email, phone.
- **News/Blog** — A few bland posts about "innovation" and "partnerships." One post mentions a "major milestone" in an unnamed internal project.

### DNS Records
- A records for boreas-systems.ctf (or whatever domain)
- MX record pointing to mail.boreas-systems.ctf
- TXT record with SPF that references internal IP ranges
- Subdomains: mail, vpn, wiki, git, scada (some resolve, some don't — encourages enumeration)

### Hidden / Non-obvious Content
- robots.txt disallows /internal/ and /admin/ paths
- /internal/ has a directory listing with a few PDFs (annual report, org chart)
- HTML comments in source contain a developer note referencing "the new procurement portal"
- An old version of the site cached at /old/ or /backup/ leaks more info

## Flags

### Flag 1 — Boreas Systems company info
- **Difficulty:** Easy
- **Location:** Company "About Us" page references a registration number. The flag is embedded in the page source as a comment near the registration number.
- **Flag:** `FLAG{8f3a2c1e9b7d4056}`
- **Mission:** M1

### Flag 2 — Employee directory / org chart
- **Difficulty:** Easy
- **Location:** PDF org chart in /internal/ directory (accessible because directory listing is on). Flag is in the document metadata or in a watermark.
- **Flag:** `FLAG{d4e7b1f283a6c950}`
- **Mission:** M1

### Flag 3 — Job posting reveals tech stack
- **Difficulty:** Easy
- **Location:** Careers page. A job posting for "Systems Integration Engineer" lists requirements including "experience with Modbus/TCP, OPC-UA, PLC programming (Allen-Bradley, Siemens S7)." The flag is in a hidden field in the application form.
- **Flag:** `FLAG{a1c9e3f7054b82d6}`
- **Mission:** M1

### Flag 4 — Client list / cover contracts
- **Difficulty:** Easy
- **Location:** The /old/ backup site has a page listing "select clients" — all fake consulting contracts. One contract references "Project L" with an unusually large budget line. Flag is in the page source.
- **Flag:** `FLAG{72b5e0d8f1a34c69}`
- **Mission:** M1

### Flag 5 — DNS records reveal internal hostnames
- **Difficulty:** Easy
- **Location:** DNS zone transfer is enabled (misconfiguration). Running `dig axfr` reveals internal hostnames including scada-gw.boreas-systems.ctf and lab-dc.boreas-systems.ctf. Flag is a TXT record.
- **Flag:** `FLAG{5e9c2a0f73b148d6}`
- **Mission:** M1

### Flag 6 — Supplier identified from public filings
- **Difficulty:** Medium
- **Location:** The annual report PDF is NOT in the /internal/ directory listing. It must be discovered by: (1) noticing the naming pattern of other documents in /internal/ (e.g., `boreas-Q1-2025.pdf`, `boreas-Q2-2025.pdf`) and brute-forcing/fuzzing the date range to find `boreas-annual-2025.pdf` at a non-linked URL, OR (2) finding a reference to the annual report URL in an HTML comment on the /old/ backup site. Once found, the annual report lists 40+ line items — most are legitimate consulting expenses. The suspicious $12M payment to "Kursk Heavy Industries" for "actuator assemblies" is buried in the middle. The flag is NOT in the PDF metadata — it is the answer to a CTFd challenge question that requires submitting the supplier name and dollar amount in the correct format (e.g., `KURSK-12000000`). This tests correlation and attention to detail, not just file discovery.
- **Flag:** `FLAG{c6f8d2b3e91a4507}` (accepted when correct supplier+amount submitted)
- **Mission:** M1, M2

---

## Build Plan

**Base image:** nginx:alpine

**Content directory:** `scenario-dev/polaris/build/A0-boreas-website/`

### Steps

1. **Build the static website (HTML/CSS/JS)**
   - Homepage, About, Leadership, Careers, Contact, News/Blog pages
   - Clean corporate template — boring consultancy aesthetic
   - Employee portal login page (non-functional, red herring)
   - `/status` maintenance page showing server info
   - HTML comments with developer notes (flag breadcrumbs)

2. **Generate leadership headshots**
   - AI-generated or stock photos for Viktor Harlan, Dr. Elena Vasik, Marcus Webb
   - Plausible corporate headshot style

3. **Create PDF documents**
   - `org_chart.pdf` — org chart with flag in metadata/watermark (flag 2)
   - `boreas-Q1-2025.pdf`, `boreas-Q2-2025.pdf` — quarterly reports (pattern for brute-forcing)
   - `boreas-annual-2025.pdf` — annual report with Kursk $12M line item buried in financials (flag 6)

4. **Build the `/old/` backup site**
   - Stripped-down version of the main site
   - "Select clients" page with Project L reference (flag 4)
   - HTML comment referencing annual report URL

5. **Build the `/internal/` directory**
   - Directory listing enabled (nginx autoindex on)
   - Contains the org chart PDF and quarterly reports
   - Annual report NOT linked here — must be fuzzed by filename pattern

6. **Configure robots.txt**
   - Disallow `/internal/` and `/admin/`

7. **Set up DNS zone file**
   - A records for boreas-systems.ctf and subdomains (mail, vpn, wiki, git, scada)
   - MX record pointing to mail.boreas-systems.ctf
   - TXT record with SPF referencing internal IP ranges
   - TXT record containing flag 5
   - Zone transfer (AXFR) enabled — this is a deliberate misconfiguration

8. **Configure nginx**
   - Serve static site on port 80
   - autoindex on for `/internal/`
   - Standard error pages

9. **Embed flags**
   - Flag 1: HTML comment near registration number on About page
   - Flag 2: PDF metadata on org chart
   - Flag 3: Hidden form field on careers application page
   - Flag 4: Page source comment on `/old/` clients page
   - Flag 5: DNS TXT record (served by companion DNS container or CoreDNS config)
   - Flag 6: CTFd challenge question — submit supplier name + amount

10. **Write Dockerfile**
    - Copy static site into nginx html root
    - Copy nginx config
    - Expose port 80

11. **DNS sidecar decision**
    - Flag 5 requires a DNS server allowing AXFR. Options: (a) CoreDNS sidecar in the shared namespace, (b) BIND in the same pod. Decide based on simplicity.
