# Polaris Asset Inventory — Speaker Outline (2–3 min)

Walkthroughs are definitive. 42 flags across ~19 assets in 6 groups.

## 1. Public / internet-facing
- Corporate website (A0), authoritative DNS, intranet wiki + webmail (A3).
- Contractor Gitea mirror (A17) and release vault (A18).

## 2. Corporate IT — Windows shop
- Active Directory domain controller (A2, Server 2022 — LDAP, Kerberos, DCSync-able).
- SMB file share (A4, Public / HR / IT / Procurement).
- Mail server (A1, Dovecot / Roundcube).

## 3. Engineering / DevOps
- Gitea source repos (A7) for the product line — navigation, assembly, weapons-integration, manufacturing-orchestrator. Deleted-commit history intact.
- Engineering workstation (A6) — Jenkins CI, simulation archives, design files.

## 4. Research / lab data
- PostgreSQL research database (A8) with compartmented schemas and SECURITY DEFINER functions.
- Analyst workstation (A16) — SSH pivot into the lab net, `.pgpass`, SSH keys.

## 5. OT / ICS — the bunker
- Splice landing box (A9) as the IT→OT jump.
- Three Modbus/TCP PLC-class controllers: tail (A10), leg (A11), arms (A12) — real registers, coils, device IDs, serials.
- "Brain" master controller (A13) on a custom binary TCP protocol with SHA256 XOR challenge-response.
- SCADA HMI gateway (A5) — web HMI on 8080, Modbus on 502, fuel / cooling / temperature logic.

## 6. Attacker + pivot surface
- Kali attack box (A14) — curl, nmap, smbclient, ldapsearch, Impacket, pymodbus, john / hashcat, psql, git, gpg.
- Ops engineer workstation (A15) — the sanctioned OT bridge, SSH pivot to SCADA.

## Arc to call out
OSINT → front-office AD / mail / SMB → lab via Gitea + research DB → bunker OT controllers → master override. IT people see a real enterprise; OT people see real Modbus and a real HMI — not simulated stubs.
