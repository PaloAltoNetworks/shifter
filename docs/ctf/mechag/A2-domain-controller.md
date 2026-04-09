# A2: Domain Controller

**Zone:** Front Office (per participant)
**Type:** Samba AD DC (or Windows AD if Samba can't support required attack paths)

## Purpose

Active Directory for the boreas.local domain. Central authentication, group policy, user/group management. Contains information about the organization's real structure vs its cover story — some accounts map to consulting roles, others have access to resources that make no sense for a consultancy. Physical security systems (badge access, guard schedules) are also domain-joined.

## Configuration

- Domain: `boreas.local`
- Samba AD DC with Kerberos (Heimdal), LDAP, DNS
- Domain functional level sufficient for Kerberoasting and basic AD attacks
- Pre-populated users, groups, OUs, and SPNs
- Group Policy Objects with some misconfigurations

## Organizational Units

```
boreas.local/
  Consulting/        -- cover story employees
  Engineering/       -- real AURORA engineers (Lab access)
  Security/          -- physical security team
  Executive/         -- Harlan, Vasik, Webb
  ServiceAccounts/   -- SPNs for Kerberoasting
  Disabled/          -- j.chen's account still here
```

## Key Accounts

| sAMAccountName | OU | Notes |
|---|---|---|
| v.harlan | Executive | Domain Admin (shouldn't be, but is) |
| e.vasik | Engineering | Member of "Lab-Access" and "Project-L" groups |
| svc-backup | ServiceAccounts | SPN: MSSQLSvc/fileserv.boreas.local. Weak password, Kerberoastable |
| svc-scada | ServiceAccounts | SPN: HTTP/scada-gw.boreas.local. Member of "SCADA-Admins" group |
| guard.petrov | Security | Account active but flagged in logs for off-hours access |
| j.chen | Disabled | Account disabled but not deleted. Still in "Engineering" group membership |

## Groups

| Group | Members | Notes |
|---|---|---|
| Domain Admins | v.harlan | CEO in DA is a misconfiguration |
| Backup Operators | svc-backup | Has SeBackupPrivilege — can dump ntds.dit |
| Lab-Access | e.vasik, 4 other engineers | Controls access to Lab zone |
| Project-L | e.vasik, m.webb | Only 2 members. Access to classified resources |
| SCADA-Admins | svc-scada, d.kowalski | Access to generator controls |
| Security-Staff | s.morrison, guard.petrov, 8 others | Physical security team |

## Security Logs / Event Data

- Badge access logs stored in a share: `\\dc\badgelogs\`
- Guard Petrov accessed the underground hatch entrance 6 times in the last month, all off-schedule
- Petrov's badge was used at 02:00-03:00 AM repeatedly — no other guards active at those times
- One log entry shows Petrov's badge at the hatch, then a 47-minute gap with no badge activity anywhere, then badge at the parking lot exit

## Flags

### Flag 14 — AD enumeration — suspicious accounts
- **Difficulty:** Medium
- **Location:** The "Project-L" group is not directly visible via standard enumeration — it is nested inside a generic "Research-Coordination" group, which itself is a member of "Engineering-Support." Discovering "Project-L" requires either recursive group enumeration (e.g., `Get-ADGroupMember -Recursive`, BloodHound, or manual LDAP queries following `memberOf` chains) or noticing that e.vasik's account has an unexplained transitive group membership. Once found, the flag is in a custom LDAP attribute (`extensionAttribute1`) on the "Project-L" group object — not a standard attribute that basic tools display by default.
- **Flag:** `FLAG{2f8b4a6c1d9e7053}`
- **Mission:** M2

### Flag 16 — Guard rotation logs — unreliable guard
- **Difficulty:** Medium
- **Location:** Badge access logs in `\\dc\badgelogs\`. Cross-referencing Petrov's access times with the guard schedule (from Morrison's email on A1) reveals the anomaly. The flag is in a log entry comment field for one of Petrov's off-hours accesses.
- **Flag:** `FLAG{b3d7e1f0c8a24596}`
- **Mission:** M1, M3

### Flag 17 — Privilege escalation — domain admin
- **Difficulty:** Hard
- **Location:** Multi-step chain required. (1) Kerberoast `svc-backup` (weak password, crackable offline). (2) `svc-backup` is NOT a Domain Admin — it has `BackupOperators` privileges, which grants `SeBackupPrivilege`. (3) Use backup privileges to extract the AD database (ntds.dit) via shadow copy or `reg save`. (4) Offline extraction of the `krbtgt` hash from the dumped ntds.dit. (5) Forge a golden ticket or crack the DA account hash. (6) Access the DA-only share `\\dc\admin$\flag.txt`. This is a realistic AD attack chain: Kerberoast → backup operator abuse → ntds.dit dump → golden ticket.
- **Flag:** `FLAG{6c0a9d4e7f2b8135}`
- **Mission:** M3
