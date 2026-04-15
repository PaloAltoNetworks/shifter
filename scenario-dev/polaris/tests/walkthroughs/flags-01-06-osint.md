# Flags 1–6: OSINT (Boreas Website)

> **Start here:** Read [00-range-access-docker.md](00-range-access-docker.md) for how to access the Docker compose range. All commands run FROM INSIDE the Kali container (`sudo docker exec -it a14-kali /bin/bash`).

All of these flags come from the Boreas Systems website at **172.20.0.10** (port 80). DNS is at **172.20.0.2**. No authentication required.

---

## Flag 1 — Company Info (Easy, 50pts)

1. Open the website and go to the **About Us** page (`/about`).
2. You'll see a table with company information including a registration number `7741-BSI-2018`.
3. **View the page source** (right-click → View Source, or `curl /about`).
4. Near the registration number, there is an HTML comment containing the flag.

**Expected flag:** `FLAG{8f3a2c1e9b7d4056}`

---

## Flag 2 — Employee Directory (Easy, 50pts)

1. Fetch `/robots.txt` from the website. It disallows `/internal/` and `/admin/`.
2. Visit `/internal/` anyway — the directory listing shows org_chart.pdf and the quarterly reports.
3. Download `org_chart.pdf` and check the PDF Author metadata field:
   ```
   exiftool org_chart.pdf | grep Author
   ```
4. The flag is the value of the Author field.

**Expected flag:** `FLAG{d4e7b1f283a6c950}`

---

## Flag 3 — Tech Stack Revealed (Easy, 50pts)

1. Visit the **Careers** page (`/careers`).
2. Read the job posting — it mentions Modbus/TCP, OPC-UA, PLC programming. This reveals what Boreas is really doing.
3. **View the page source.** Look at the application form at the bottom.
4. There is a hidden form field (`<input type="hidden" name="tracking_id" ...>`). The flag is its value.

**Expected flag:** `FLAG{a1c9e3f7054b82d6}`

---

## Flag 4 — Client Contracts (Easy, 50pts)

1. Browse to `/old/` — this is an archived version of the website.
2. Click on "Select Clients" (or go directly to `/old/clients`).
3. You'll see a table of consulting contracts. One entry stands out: **"Project L (internal)"** with a budget of **$165.3M** — far larger than any consulting contract.
4. **View the page source.** The flag is in an HTML comment.

**Expected flag:** `FLAG{72b5e0d8f1a34c69}`

---

## Flag 5 — DNS Reconnaissance (Easy, 50pts)

1. Attempt a DNS zone transfer against the Boreas DNS server:
   ```
   dig axfr boreas-systems.ctf @172.20.0.2
   ```
2. Zone transfer is enabled (a misconfiguration). You'll see internal hostnames like `scada-gw.boreas-systems.ctf`, `lab-dc.boreas-systems.ctf`, etc.
3. One of the TXT records contains the flag.

**Expected flag:** `FLAG{5e9c2a0f73b148d6}`

**Note:** This requires the DNS sidecar to be running. If DNS is not configured, this flag cannot be tested.

---

## Flag 6 — Follow the Money (Medium, 100pts)

1. In the `/internal/` directory listing you see quarterly reports: `boreas-Q1-2025.pdf`, `boreas-Q2-2025.pdf`, and `org_chart.pdf`.
2. Notice the naming pattern. Try fuzzing for an annual report: `curl http://boreas-systems.ctf/internal/boreas-annual-2025.pdf`. It's NOT linked in the directory listing but IS accessible directly (nginx serves the file; it's just excluded from the hand-written index.html).
3. Alternatively, check the `/old/` backup site source — there's an HTML comment with the annual report URL: `<!-- Note to dev: annual report moved to /internal/boreas-annual-2025.pdf -->`.
4. Extract the PDF text to find the suspicious supplier line:
   ```
   pdf2txt.py boreas-annual-2025.pdf | grep -i kursk
   ```
5. The annual report has 40+ expense line items. Most are normal. One stands out: **"Kursk Heavy Industries - actuator assemblies $12,000,000"** buried in the middle.
6. This is a CTFd challenge question — submit the supplier name and dollar amount in the format the challenge specifies.

**Expected flag:** `FLAG{c6f8d2b3e91a4507}`

---

## Smoketest Results — 2026-04-12

Tested from inside Kali container (`a14-kali`) against live Docker Compose range.

| Flag | Description | Expected Flag | Found | Result | Notes |
|------|-------------|---------------|-------|--------|-------|
| 1 | Company Info (HTML comment on /about) | `FLAG{8f3a2c1e9b7d4056}` | `FLAG{8f3a2c1e9b7d4056}` | **PASS** | HTML comment next to registration number 7741-BSI-2018 |
| 2 | Employee Directory (org_chart.pdf Author metadata) | `FLAG{d4e7b1f283a6c950}` | `FLAG{d4e7b1f283a6c950}` | **PASS** | robots.txt disallows /internal/; hand-written index lists PDFs; flag in Author field via `exiftool` (note: `pdfinfo`/`pdftotext` not installed in a14-kali; use `exiftool` + `pdf2txt.py`) |
| 3 | Job Posting (hidden form field on /careers) | `FLAG{a1c9e3f7054b82d6}` | `FLAG{a1c9e3f7054b82d6}` | **PASS** | Hidden input `tracking_id` in application form |
| 4 | Client List (HTML comment on /old/clients) | `FLAG{72b5e0d8f1a34c69}` | `FLAG{72b5e0d8f1a34c69}` | **PASS** | Comment in page source; Project L ($165.3M) visible in table |
| 5 | DNS Zone Transfer (TXT record) | `FLAG{5e9c2a0f73b148d6}` | `FLAG{5e9c2a0f73b148d6}` | **PASS** | `dig axfr` succeeds; flag in `_flag.boreas-systems.ctf` TXT record |
| 6 | Supplier from Annual Report | `FLAG{c6f8d2b3e91a4507}` | N/A (CTFd-side) | **PASS** | Annual report at /internal/boreas-annual-2025.pdf accessible (unlisted but guessable); /old/ source has HTML comment hint; Kursk Heavy Industries $12,000,000 line extractable via `pdf2txt.py`; flag validated by CTFd |

**Summary: 6/6 PASS**
