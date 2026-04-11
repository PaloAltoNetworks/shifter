# Flags 1–6: OSINT (Boreas Website)

> **Start here:** Read [00-range-access.md](00-range-access.md) first for SSH instructions, how to start services, ports, and credentials.

All of these flags come from the public Boreas Systems website (`$A0_URL`, default `http://127.0.0.1:8082`). No authentication required.

---

## Flag 1 — Company Info (Easy, 50pts)

1. Open the website and go to the **About Us** page (`/about`).
2. You'll see a table with company information including a registration number `7741-BSI-2018`.
3. **View the page source** (right-click → View Source, or `curl /about`).
4. Near the registration number, there is an HTML comment containing the flag.

**Expected flag:** `FLAG{8f3a2c1e9b7d4056}`

---

## Flag 2 — Employee Directory / Org Chart (Easy, 50pts)

1. Fetch `/robots.txt` from the website. It disallows `/internal/` and `/admin/`.
2. Visit `/internal/` anyway. Directory listing is enabled — you'll see files listed.
3. Download `org_chart.txt` (in production this will be a PDF — check the Author metadata field with `exiftool` or `pdfinfo`).
4. The flag is embedded in the document metadata.

**Expected flag:** `FLAG{d4e7b1f283a6c950}`

---

## Flag 3 — Job Posting Reveals Tech Stack (Easy, 50pts)

1. Visit the **Careers** page (`/careers`).
2. Read the job posting — it mentions Modbus/TCP, OPC-UA, PLC programming. This reveals what Boreas is really doing.
3. **View the page source.** Look at the application form at the bottom.
4. There is a hidden form field (`<input type="hidden" name="tracking_id" ...>`). The flag is its value.

**Expected flag:** `FLAG{a1c9e3f7054b82d6}`

---

## Flag 4 — Client List / Cover Contracts (Easy, 50pts)

1. Browse to `/old/` — this is an archived version of the website.
2. Click on "Select Clients" (or go directly to `/old/clients`).
3. You'll see a table of consulting contracts. One entry stands out: **"Project L (internal)"** with a budget of **$165.3M** — far larger than any consulting contract.
4. **View the page source.** The flag is in an HTML comment.

**Expected flag:** `FLAG{72b5e0d8f1a34c69}`

---

## Flag 5 — DNS Records (Easy, 50pts)

1. Attempt a DNS zone transfer against the Boreas DNS server:
   ```
   dig axfr boreas-systems.ctf @<dns-server-ip>
   ```
2. Zone transfer is enabled (a misconfiguration). You'll see internal hostnames like `scada-gw.boreas-systems.ctf`, `lab-dc.boreas-systems.ctf`, etc.
3. One of the TXT records contains the flag.

**Expected flag:** `FLAG{5e9c2a0f73b148d6}`

**Note:** This requires the DNS sidecar to be running. If DNS is not configured, this flag cannot be tested.

---

## Flag 6 — Supplier Identified from Public Filings (Medium, 100pts)

1. In the `/internal/` directory, you see quarterly reports: `boreas-Q1-2025.txt`, `boreas-Q2-2025.txt`.
2. Notice the naming pattern. Try fuzzing for an annual report: `boreas-annual-2025.txt`. It's NOT linked in the directory listing but IS accessible at `/internal/boreas-annual-2025.txt`.
3. Alternatively, check the `/old/` backup site source — there's an HTML comment with the annual report URL.
4. The annual report has 40+ expense line items. Most are normal. One stands out: **"Kursk Heavy Industries — actuator assemblies: $12,000,000"**.
5. This is a CTFd challenge question — submit the supplier name and dollar amount in the format the challenge specifies.

**Expected flag:** `FLAG{c6f8d2b3e91a4507}` (accepted when correct answer submitted to CTFd)
