# Flag Smoketests

Step-by-step walkthroughs for every flag. Written for someone (human or agent) who has never seen the range before. Each walkthrough describes exactly what to do, what you should see, and what the flag is.

## Environment

You are on a Kali attack box. You have access to:

- **Website:** `http://boreas-systems.ctf` (or `$A0_URL`)
- **Intranet:** `http://intranet.boreas.local` (or `$A3_URL`)
- **Ops workstation:** `ops-eng01.boreas.local` (A15, SSH) — pivot to SCADA
- **Research analyst workstation:** `analyst01.boreas.local` (A16, SSH) — pivot to Lab
- **SCADA HMI:** `http://scada-gw.boreas.local:8080` (or `$A5_URL`) after the A15 pivot
- **Gitea:** `http://git.boreas.local:3000` (or `$A7_URL`) after the A16 pivot
- **Domain Controller:** `dc01.boreas.local` (or `$A2_HOST`)
- **Engineering Workstation:** `eng-ws01.boreas.local` (SSH)
- **Research Database:** `researchdb.boreas.local` (PostgreSQL port 5432)
- **File Share:** `fileserv.boreas.local` (SMB ports 139/445)
- **Mail Server:** `mail.boreas.local` (IMAP/Webmail)
- **Bunker controllers:** `172.20.50.10-12` (Modbus/TCP 502), `172.20.50.50` (TCP 9100)

Standard tools: `curl`, `nmap`, `smbclient`, `ldapsearch`, `python3`, `pymodbus`, `git`, `gpg`, `psql`, Impacket suite (`GetUserSPNs.py`, `secretsdump.py`), `john`, `hashcat`
