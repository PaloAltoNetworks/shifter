# A2: Domain Controller

**Zone:** Front Office (per participant)
**Type:** Windows Server 2022 AD DC (shared VM)

## Purpose

Active Directory for the boreas.local domain. Central authentication, group policy, user/group management. Contains information about the organization's real structure vs its cover story — some accounts map to consulting roles, others have access to resources that make no sense for a consultancy. Physical security systems (badge access, guard schedules) are also domain-joined.

## Configuration

- Domain: `boreas.local`
- Windows AD DS with Kerberos, LDAP, DNS
- Domain functional level sufficient for Kerberoasting, recursive group enumeration, and DCSync
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

### Flag 14 — Hidden Group
- **Difficulty:** Medium
- **Location:** The "Project-L" group is not directly visible via standard enumeration — it is nested inside a generic "Research-Coordination" group, which itself is a member of "Engineering-Support." Discovering "Project-L" requires either recursive group enumeration (e.g., `Get-ADGroupMember -Recursive`, BloodHound, or manual LDAP queries following `memberOf` chains) or noticing that e.vasik's account has an unexplained transitive group membership. Once found, the flag is in the `info` LDAP attribute on the "Project-L" group object — not a standard attribute that basic tools display by default.
- **Flag:** `FLAG{2f8b4a6c1d9e7053}`
- **Mission:** Mission 2 — Inside Boreas

### Flag 16 — Unreliable Guard
- **Difficulty:** Medium
- **Location:** Badge access logs in `\\dc\badgelogs\`. Cross-referencing Petrov's access times with the guard schedule (from Morrison's email on A1) reveals the anomaly. The flag is in a log entry comment field for one of Petrov's off-hours accesses.
- **Flag:** `FLAG{b3d7e1f0c8a24596}`
- **Mission:** Mission 2 — Inside Boreas

### Flag 17 — Domain Admin
- **Difficulty:** Hard
- **Location:** Multi-step chain required. (1) Kerberoast `svc-backup` (weak password, crackable offline with John/Hashcat). (2) `svc-backup` has misconfigured DCSync rights (Replicating Directory Changes ACL) — the IT admin granted replication rights for a backup sync tool. (3) Use `secretsdump.py` with svc-backup's cracked credentials to DCSync the Administrator hash. (4) Use pass-the-hash or crack the DA password to access the DA-only share `\\dc\admin_flag\flag.txt`. Alternative: DCSync the krbtgt hash and forge a golden ticket. This is a realistic AD attack chain: Kerberoast → crack → DCSync (over-privileged service account) → DA access.
- **Flag:** `FLAG{6c0a9d4e7f2b8135}`
- **Mission:** Mission 2 — Inside Boreas

---

## Build Plan

**Platform:** Windows Server 2022 Core on GCE (shared VM, not per-participant)
**GCE Image:** `ctf-a2-windc-base-v1` (family: `ctf-a2-windc`) — pre-configured, boots ready in ~2 min
**Spike notes:** `temp/a2-samba-ad-spike.md`
**Content directory:** `scenario-dev/polaris/build/A2-domain-controller/`

### Why Windows, Not Samba

Samba AD DC was tested and cannot support standard AD attack tooling:
- Impacket Kerberoasting fails (KRB_AP_ERR_INAPP_CKSUM — Samba KDC rejects Impacket TGS-REQ)
- Impacket secretsdump/DCSync fails (DRSUAPI not compatible)
- AS-REP roasting fails (Samba KDC ignores DONT_REQUIRE_PREAUTH)
- Full details in `temp/a2-samba-ad-spike.md`

### What's Already Built (in the custom image)

1. **Domain:** `BOREAS.LOCAL` (Windows Server 2022, WinThreshold functional level)
2. **OUs:** Consulting, Engineering, Security, Executive, ServiceAccounts, Disabled
3. **23 user accounts** with correct OU placement, passwords per spec
4. **Groups with nesting:** Engineering-Support > Research-Coordination > Project-L (e.vasik, m.webb)
5. **SPNs:** svc-backup (`MSSQLSvc/fileserv.boreas.local`), svc-scada (`HTTP/scada-gw.boreas.local`)
6. **DCSync rights** on svc-backup (misconfigured Replicating Directory Changes ACL)
7. **Flag 14:** `info` attribute on Project-L group (not `extensionAttribute1` — Exchange schema not available)
8. **Flag 16:** Badge log CSV in `\\dc\badgelogs\` share with Petrov anomaly entries
9. **Flag 17:** DA-only `\\dc\admin_flag\` share containing flag file
10. **Windows Firewall:** Disabled (all profiles)

### Validated Attack Chain (flag 17)

```
GetUserSPNs.py → $krb5tgs$23$ hash for svc-backup
John/Hashcat → Password1 (cracks in <5 min)
secretsdump.py as svc-backup → Administrator NTLM hash
smbclient to admin_flag share → FLAG{6c0a9d4e7f2b8135}
```

### Deployment Steps (event day)

1. Launch VM from custom image: `gcloud compute instances create ... --image-family=ctf-a2-windc`
2. Wait ~2 min for AD DS to start
3. Set Administrator password via startup script or `gcloud compute reset-windows-password`
4. Verify with `smbclient -L //host -U "BOREAS\Administrator%password"`

### Remaining Work

1. Add more realistic badge log data (more normal guard entries, longer date range)
2. Add filler documents to SYSVOL/NETLOGON shares for realism
3. Test from actual Kali container (not just Debian with Impacket)
4. Verify `john --wordlist=rockyou.txt` cracks `Password1` hash in <5 min
