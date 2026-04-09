# A1: Mail Server

**Zone:** Front Office (per participant)
**Type:** Email server (e.g., Postfix/Dovecot, Roundcube webmail, or similar)

## Purpose

Boreas Systems corporate email. Contains employee correspondence that reveals the organization's internal culture, hints at PROJECT LEVIATHAN, and provides credentials for lateral movement. The terminated engineer's email trail is one of the key narrative threads.

## Configuration

- SMTP/IMAP services running
- Webmail interface (Roundcube or similar) on port 80/443
- Multiple mailboxes pre-populated with realistic email chains
- Weak/reused passwords on some accounts
- No email filtering or DLP (it's a poorly secured front company)

## Accounts

| Username | Password | Role |
|----------|----------|------|
| v.harlan | `Boreas2025!` | CEO, sparse emails, mostly forwards |
| e.vasik | `Reactor#Core9` | CTO, technical emails about "the project" |
| m.webb | `Welcome1` | COO, procurement and logistics |
| j.chen | `Summer2024` | Engineer (terminated), inbox still active |
| d.kowalski | `P@ssw0rd123` | IT admin, has internal system creds in sent mail |
| s.morrison | `Br3ach!ng` | Security team lead, guard schedules |

## Email Content

### Viktor Harlan (CEO)
- Forwards from "the board" about timeline pressures
- One email to Vasik: "Elena — where are we on the locomotion milestone? The principals are asking."
- Corporate mundane: holiday schedule, all-hands meeting notes

### Dr. Elena Vasik (CTO)
- Technical thread with Lab team about simulation results: "MIDNIGHT-7 exceeded all projections. Bipedal stability at 120m is achievable."
- Email to procurement requesting "expedited delivery of the Kursk shipment — we cannot slip the integration window"
- Reply to Harlan: "Locomotion is 100%. Weapons integration is on track. We are waiting on the primary power source."

### James Chen (terminated engineer)
- Thread with his manager asking about PO-2847 (hydraulic actuators rated for 200 tons): "This doesn't match any client project I'm aware of. What is this for?"
- Manager reply: "That's above your clearance. Focus on your assigned deliverables."
- Follow-up from Chen: "I pulled the specs on the actuators. These are rated for something enormous. Is this a weapons program?"
- Final email: HR termination notice. "Your employment is terminated effective immediately. Your access has been revoked."

### Dariusz Kowalski (IT admin)
- Sent email to self with subject "creds backup" containing credentials for the wiki admin panel and file share service account
- Ticket thread about setting up the SCADA network segment: "Isolated the generator controls on VLAN 40. Access via scada-gw.internal."

### Sarah Morrison (Security lead)
- Guard rotation spreadsheet attachment
- Email thread about "unusual access patterns" from Guard #7 (the unreliable guard narrative thread)
- Note to Harlan: "Recommend we terminate Guard Petrov. His access logs don't match his patrol schedule."

## Flags

### Flag 8 — Employee email with project hints
- **Difficulty:** Easy
- **Location:** Vasik's email to Harlan about locomotion milestone. Flag is in an email attachment (a 1-page status report PDF). The flag is in the PDF content.
- **Flag:** `FLAG{3b7e9a2d1c8f4063}`
- **Mission:** M1, M2

### Flag 10 — Password reuse gives mail access
- **Difficulty:** Easy
- **Location:** Log into the webmail as d.kowalski using `P@ssw0rd123` (discoverable from A0's employee directory + common password guessing, or from a config file on A3). The flag is in Kowalski's inbox, in a "welcome to your new mailbox" auto-generated email.
- **Flag:** `FLAG{e5d1f8c2a7b03946}`
- **Mission:** M1

### Flag 15 — Lateral movement to second host
- **Difficulty:** Medium
- **Location:** Kowalski's "creds backup" email contains service account credentials for the file share (A4). The flag is NOT in the email — it is on A4 in a share (`\\fileshare\IT\backup_verification.log`) that is only accessible using the service account credentials from this email. Requires actually authenticating to A4 via SMB with the discovered creds and navigating a restricted share. The flag is in the log file.
- **Flag:** `FLAG{9a4c7e2f58d0b163}`
- **Mission:** M3
