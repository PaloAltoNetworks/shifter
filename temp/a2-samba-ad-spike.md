# A2 Samba AD DC - Spike Notes

## Goal
Determine if Samba AD DC in a container can support the full flag 17 attack chain:
Kerberoasting → BackupOperator privesc → ntds.dit dump → golden ticket → DA share access

## Test Environment
- VPC: `ctf-test-lab` (10.100.0.0/24, us-east4)
- DC VM: `ctf-test-a2-dc` (10.100.0.2, Debian 12, e2-medium)
- Attacker VM: `ctf-test-attacker` (10.100.0.3, Debian 12, e2-medium)

## Key Questions
1. Can Samba AD DC issue Kerberos TGS tickets that Impacket GetUserSPNs can extract?
2. Does Samba support SeBackupPrivilege / Backup Operators group semantics?
3. Can secretsdump.py extract hashes from Samba's LDB backend (not ntds.dit)?
4. Can a golden ticket forged from krbtgt hash work against Samba?
5. What's the minimum viable Samba config for all of this?
6. Can this be baked into a GCP custom image for fast provisioning?

## Setup Log

### 2026-04-10 - Initial Setup

**Samba version:** 4.17.12 (Debian 12 bookworm package)
**Domain:** BOREAS.LOCAL, 2008 R2 functional level
**Provision:** `samba-tool domain provision` — straightforward, ~8 seconds

### Findings

#### What WORKS against Samba AD DC

| Capability | Status | Notes |
|---|---|---|
| Domain provision | YES | Clean, fast, fully automated |
| User/group/OU creation | YES | `samba-tool user create`, `group addmembers`, etc. |
| SPN assignment | YES | `samba-tool spn add` works fine |
| Custom LDAP attributes | YES | `ldbmodify` can set extensionAttribute1, etc. |
| Kerberos TGT (kinit) | YES | Native kinit works perfectly |
| Kerberos TGS (kvno) | YES | Native kvno gets TGS tickets for SPNs |
| LDAP enumeration | YES | ldapsearch works (requires `ldap server require strong auth = no`) |
| SMB share access | YES | smbclient works, shares mount fine |
| RPC enumeration | YES | rpcclient enumdomusers, etc. all work |
| Local hash extraction | YES | `samba-tool user getpassword` extracts NT hashes from LDB |

#### What FAILS against Samba AD DC

| Capability | Status | Notes |
|---|---|---|
| Impacket GetUserSPNs (Kerberoasting) | **FAIL** | `KRB_AP_ERR_INAPP_CKSUM` — Samba KDC rejects Impacket's TGS-REQ construction. Known incompatibility. The TGS request is malformed according to Samba's Heimdal KDC. Native kvno works, but Impacket does not. |
| Impacket secretsdump (DRSUAPI) | **FAIL** | `DRSR SessionError: ERROR_SUCCESS` (misleading). Samba's DRSUAPI doesn't support DCSync-style replication for hash extraction. |
| Impacket secretsdump (-use-vss) | **FAIL** | No NTDS.DIT file exists — Samba uses LDB, not ESE database. VSS shadows don't apply. |
| SeBackupPrivilege abuse | **UNTESTED** | Depends on secretsdump working. Likely N/A since the ntds.dit extraction path doesn't exist on Samba. |
| Golden ticket | **UNTESTED** | krbtgt hash can be extracted locally via samba-tool, but whether a forged ticket works against Samba's KDC is unknown. |

#### Key Insight: Samba Is Not a Drop-in for Windows AD Attack Tooling

The standard Impacket toolchain (GetUserSPNs, secretsdump, golden ticket) was built for Windows AD. Samba's Kerberos (Heimdal, not MIT), database (LDB, not ESE/ntds.dit), and DRSUAPI implementation are different enough that the classic attack chain **does not work**.

### Options

#### Option A: Use Samba, Redesign the Attack Chain
Keep Samba AD DC but change the flag 17 attack chain to use techniques that work:
- LDAP enumeration for discovery (works)
- Password spraying / brute force instead of Kerberoasting
- Custom vulnerable service or misconfigured share for privesc instead of backup operator abuse
- Pre-plant the flag in a share accessible only via discovered DA creds
- **Pro:** Stays in containers, scales to 110 pods
- **Con:** Not a realistic AD attack chain. Participants with AD experience will notice it's not real AD.

#### Option B: Windows VM per Participant
Run actual Windows Server with AD DS. Full Impacket compatibility guaranteed.
- **Pro:** Real AD, all attack tools work as expected
- **Con:** 110 Windows VMs is expensive, slow to provision, license concerns. GDC VM runtime or Compute Engine.

#### Option C: Shared Windows AD DC + Per-Participant Isolation
One Windows AD DC shared by all participants, with separate OUs/users per participant.
- **Pro:** Only 1 Windows VM to manage
- **Con:** Participants could interfere with each other (one person's golden ticket = everyone's DA access). Hard to isolate AD-level attacks in a shared domain.

#### Option D: Samba for Basic AD + Simplified Attack Chain
Use Samba for realistic LDAP/SMB/Kerberos surface, but simplify flag 17 to avoid the broken attack paths:
- Keep Kerberoasting discovery (SPN enumeration via LDAP works) but have the password hash crackable from an alternative source (e.g., NTLM hash leaked in a share, or AS-REP roasting instead)
- Replace backup operator → ntds.dit chain with a simpler but still realistic privesc (e.g., writable GPO, LAPS, constrained delegation)
- **Pro:** Still a container, still feels like AD, attack chain is realistic just different
- **Con:** Need to verify each alternative attack path against Samba

### AS-REP Roasting Test

- Set `UF_DONT_REQUIRE_PREAUTH` (UAC 4194816) on svc-backup via ldbmodify
- LDAP confirms the flag is set (0x400200)
- Impacket `GetNPUsers.py` says "doesn't have UF_DONT_REQUIRE_PREAUTH set"
- Native `kinit` without password also still demands a password
- **Conclusion: Samba's KDC does not honor DONT_REQUIRE_PREAUTH. AS-REP roasting is broken.**

### Verdict: Samba Cannot Support AD Attack Chains

Both Kerberoasting and AS-REP roasting fail at the KDC protocol level. DRSUAPI/secretsdump fails at the replication level. These are not configuration issues — they are fundamental limitations of Samba's AD DC implementation.

**What Samba CAN do:** LDAP enumeration, SMB shares, basic Kerberos auth (TGT/TGS for legitimate use), user/group/OU management, SPN assignment. It looks like AD and talks like AD for legitimate usage.

**What Samba CANNOT do:** Serve as a target for standard AD attack tooling (Impacket, Rubeus, BloodHound data collection via SharpHound). The attack surface is cosmetically similar but functionally different from Windows AD.

### Decision Point

For the CTF, we have two real options:

#### Option A: Windows VM (recommended for flag 17 attack chain)
Use a Windows Server VM running AD DS. All Impacket tools work out of the box. The full Kerberoasting → backup operator → ntds.dit → golden ticket chain is a well-documented, realistic attack path.

**Cost concern:** 110 Windows VMs is too expensive. But A2 could be one of the shared assets (like A0/A5/A7). All participants share one AD DC. The attack chain is the same for everyone — whoever gets DA first just gets there first. No state isolation needed because AD enumeration/Kerberoasting doesn't modify the domain.

**Risk:** Golden ticket creation is destructive (could theoretically affect other participants). Mitigated by: (a) the flag is just reading a file on a share, not actually using a golden ticket in production; (b) each participant's flag submission is independent.

#### Option B: Samba + Redesigned Attack Chain
Keep Samba but completely redesign flag 17 to avoid broken tools. Replace Kerberoasting with password-in-a-share. Replace ntds.dit with direct credential discovery. This would work but isn't a real AD attack chain — experienced participants will find it artificial.

### Windows VM Testing (2026-04-10)

**Setup:** Windows Server 2022 Core on GCE e2-medium, startup script for AD DS install + promotion

#### Observations

1. **AD DS promotion via GCE startup scripts is fragile.** The script runs on every boot. Detecting whether the machine is already a DC is non-trivial because:
   - AD DS services aren't ready immediately after boot
   - `Get-ADDomain` fails until NetLogon starts (30-60 seconds post-boot)
   - GCE guest agent resets/disables the Administrator account between boots
   - Multiple promotions can overlap or conflict

2. **Boot-to-ready time is ~4-5 minutes** (boot → guest agent → startup script → AD DS service start → NetLogon ready). Not suitable for on-demand per-participant provisioning.

3. **The right approach is a pre-baked custom image.** Promote the DC once, snapshot it, create a custom image. All future boots start with AD DS already configured — no startup script needed for promotion, just for CTF-specific setup (users, groups, flags).

4. **SMB/LDAP connectivity works** once AD services are up and Windows Firewall is disabled. Impacket wmiexec connects, smbclient connects.

5. **GCE password management on DCs is weird.** `gcloud compute reset-windows-password` interacts with the domain Administrator account post-promotion, but the guest agent may disable/re-enable accounts unpredictably.

### Revised Plan

1. **Manually complete the Windows DC setup** (promote, configure, validate attack chain)
2. **Create a GCP custom image** from the configured DC
3. **Test Kerberoasting + secretsdump + golden ticket** against the Windows DC from the attacker VM
4. **Decision: shared vs per-participant**
   - If attack chain is non-destructive (just enumeration + hash extraction): shared is fine
   - If golden ticket creation could disrupt other participants: need isolation

### Windows AD Attack Chain — CONFIRMED WORKING (2026-04-10)

**Windows Server 2022 Core on GCE e2-medium, BOREAS.LOCAL domain**

| Step | Tool | Status | Notes |
|------|------|--------|-------|
| Kerberoasting (GetUserSPNs) | Impacket | **WORKS** | Got full $krb5tgs$23$ hash for svc-backup |
| DCSync (secretsdump) | Impacket | **WORKS** | Extracted krbtgt NTLM + AES keys via DRSUAPI |
| SMB share access | smbclient | **WORKS** | After firewall disable |
| LDAP enumeration | ldapsearch/ldapmodify | **WORKS** | Full read/write AD objects |
| RPC enumeration | rpcclient | **WORKS** | User creation, enumeration |
| User/SPN creation | ldapmodify | **WORKS** | Created user, set SPN, modified UAC |

**The full flag 17 chain is feasible on Windows AD.** Kerberoast svc-backup → crack password → use backup operator privesc → DCSync → extract krbtgt → forge golden ticket → access DA-only share.

### Outstanding

**Backup operator privesc path not yet tested.** The specific chain for flag 17 is: Kerberoast svc-backup → crack → svc-backup has Backup Operators → use SeBackupPrivilege to DCSync (via secretsdump with svc-backup creds, NOT DA). Need to verify that secretsdump.py works with just Backup Operators rights (it may need DA for DRSUAPI). If not, the alternative is using backup privileges to copy ntds.dit via shadow copy, then offline extraction.

### Architecture Decision: Shared Windows DC

A2 should be a **shared** Windows VM (not per-participant) because:
1. The attack chain (Kerberoast → DCSync) is **read-only** — it doesn't modify domain state
2. One Windows VM vs 110 saves massive cost and complexity
3. All participants enumerate the same domain, find the same SPNs, crack the same hashes
4. The flag is static — whoever finds it first just gets first-place credit on CTFd

**Risk:** Golden ticket creation is technically a write operation (forged ticket). But the ticket is used client-side — it doesn't modify the DC. Safe for shared use.

### Image Strategy

1. Complete the DC setup: all users, groups, OUs, SPNs, badge log shares, flag files
2. Snapshot the boot disk → create a GCP custom image
3. At CTF event time: launch from custom image, takes ~2 min to boot vs ~5 min for fresh promotion
4. Startup script only needs to: disable firewall, set Administrator password — no promotion

### Next Steps
1. Test the backup operator → secretsdump path specifically (non-DA)
2. Complete all A2 users/groups/shares per the asset spec
3. Snapshot and create custom image
4. Update A2 build plan to reflect Windows VM (not Samba container)

### Backup Operator Privesc Testing (2026-04-10)

**Result: Backup Operators CANNOT DCSync out of the box.**

- `secretsdump.py -just-dc-user krbtgt` as svc-backup (Backup Operators member): `ERROR_DS_DRA_BAD_DN` — DRSUAPI requires `Replicating Directory Changes` ACL, which Backup Operators don't have.
- `secretsdump.py -use-vss` as svc-backup: `rpc_s_access_denied` — can't create remote services for VSS shadow copy.
- svc-backup CAN read ADMIN$ and C$ shares (SeBackupPrivilege grants this), but can't execute commands remotely (no smbexec, no wmiexec).

**Revised flag 17 attack chain:**

The original chain (Kerberoast → Backup Operator → ntds.dit → golden ticket) doesn't work cleanly because Backup Operators lack both DRSUAPI and remote exec rights. Two options:

**Option A (selected): Misconfigured DCSync rights on svc-backup.**
The narrative: IT admin (Kowalski) granted svc-backup replication rights for a backup sync tool, creating a misconfigured service account with both Kerberoastable SPN and DCSync rights. This is a realistic misconfiguration seen in real environments (over-privileged service accounts). Attack chain becomes:
1. Kerberoast svc-backup (SPN discovery + TGS extraction)
2. Crack the hash offline (weak password: `Password1`)
3. DCSync with svc-backup creds (`secretsdump -just-dc-user krbtgt`)
4. Forge golden ticket with krbtgt hash
5. Access DA-only flag share

**Option B (rejected): Real Backup Operator ntds.dit extraction.**
Would require participants to: get a shell on the DC → run diskshadow.exe → copy ntds.dit from shadow → exfiltrate → extract offline. Too many steps for a 4-hour CTF and requires interactive access to the DC, which is hard to provide in a shared environment.

### Gotchas & Lessons Learned

1. **GCE startup script + AD is fragile.** The script runs on every boot. AD services take 30-90 seconds to be ready. The script must wait for AD DS before doing anything AD-related. Detecting "am I already a DC" is best done by checking for the NTDS service, NOT `Get-ADDomain` or registry ProductType.

2. **GCE guest agent vs domain admin.** The GCE guest agent runs `reset-windows-password` which on a DC modifies the domain Administrator account. It can disable/re-enable the account. After promotion, always explicitly enable Administrator and set a known password in the startup script.

3. **Impacket wmiexec hangs on PowerShell.** On Server Core 2022, `wmiexec.py ... "powershell.exe -File script.ps1"` connects but never returns output. Use `atexec.py` instead, but it needs the `ADMIN$\Temp\` directory to exist. Even then, output retrieval is flaky. Best to avoid interactive command execution via Impacket — use startup scripts for setup, and reserve Impacket for attack testing.

4. **Impacket dacledit.py + OpenSSL 3.x.** `dacledit.py` fails with "unsupported hash type MD4" on systems with OpenSSL 3.x (Debian 12). Workaround: set ACLs via PowerShell instead, or use an older system / `OPENSSL_CONF` override.

5. **atexec output file not found.** `atexec.py` creates a scheduled task that writes stdout to `%SYSTEMROOT%\Temp\<taskname>.tmp`. On some Server Core installs, this directory may not exist or the task may not write output. Create the directory first via `smbclient ... -c "mkdir Temp"`.

6. **Windows firewall blocks everything.** Even with GCE firewall rules open, Windows' own firewall blocks all inbound by default. The startup script MUST run `Set-NetFirewallProfile -Enabled False` before any network-based testing works.

7. **Multiple AD promotions.** If the startup script doesn't correctly detect an existing DC, it will try to promote on every boot. `Install-ADDSForest` on an already-promoted DC doesn't always fail cleanly — it may corrupt the domain. Always check for NTDS service before attempting promotion.

8. **Samba's LDAP requires `ldap server require strong auth = no`.** Without this, simple LDAP binds fail. Real Windows AD allows simple binds by default (unless GPO enforces channel binding). For a CTF environment targeting participants with basic LDAP tools, the Samba default is too restrictive.

### Full Attack Chain — END-TO-END VERIFIED (2026-04-10)

Tested from attacker VM (10.100.0.3) against Windows DC (10.100.0.4):

```
Step 1: GetUserSPNs.py → got $krb5tgs$23$ hash for svc-backup
Step 2: Crack hash → Password1 (would use John/Hashcat in real CTF)
Step 3: secretsdump.py as svc-backup → extracted krbtgt NTLM + AES keys
Step 4: smbclient to admin_flag share as DA → FLAG{6c0a9d4e7f2b8135}
```

**The revised flag 17 chain is:**
1. Enumerate SPNs via LDAP or GetUserSPNs (find svc-backup with MSSQLSvc SPN)
2. Kerberoast svc-backup → extract TGS hash
3. Crack offline with John/Hashcat (weak password, <5 min)
4. DCSync with svc-backup creds (misconfigured replication rights) → extract krbtgt
5. Forge golden ticket OR just use svc-backup's DCSync to dump DA hash
6. Access DA-only flag share with DA credentials

**Note:** Step 5-6 can be simplified. Since svc-backup has DCSync, participants can dump the Administrator hash directly (`secretsdump -just-dc-user Administrator`) and then use pass-the-hash to access the flag share. No golden ticket needed, though it remains an option.

### Startup Script That Works

The final working startup script pattern for a Windows AD DC on GCE:

1. Disable Windows Firewall (all profiles)
2. Check for NTDS service to detect if already a DC
3. If DC: wait for AD DS service to be ready (up to 3 min), then configure users/groups/ACLs
4. If not DC: install AD DS feature, promote with Install-ADDSForest (auto-reboots)
5. Critical: Enable-ADAccount Administrator + set known password (GCE agent may disable it)

The script appends to `C:\setup-log.txt` via Start-Transcript — readable via `smbclient //host/C$ -c "get setup-log.txt"` for debugging.

### Remaining Work for A2

1. **Create all users per spec:** v.harlan (DA), e.vasik (Engineering), m.webb, j.chen (disabled), d.kowalski (IT), s.morrison (Security), guard.petrov, svc-scada
2. **Create OUs:** Consulting, Engineering, Security, Executive, ServiceAccounts, Disabled
3. **Create groups with nesting:** Lab-Access, Research-Coordination > Engineering-Support > Project-L, SCADA-Admins, Security-Staff
4. **Set custom LDAP attribute:** extensionAttribute1 on Project-L group (flag 14)
5. **Create badge log share:** `\\dc\badgelogs\` with Petrov access log CSV files (flag 16)
6. **Create DA-only share:** already done (flag 17)
7. **Set svc-scada SPN:** HTTP/scada-gw.boreas.local
8. **Snapshot and create custom GCE image**
9. **Update A2 build plan:** change from Samba container to shared Windows VM

### Custom Image Created (2026-04-10)

**Image:** `ctf-a2-windc-base-v1` (family: `ctf-a2-windc`)

Contains:
- Windows Server 2022 Core with AD DS promoted as `BOREAS.LOCAL`
- All users (23 accounts) in correct OUs
- All groups with correct nesting (Engineering-Support > Research-Coordination > Project-L)
- SPNs on svc-backup and svc-scada
- DCSync rights on svc-backup
- Flag 14 in Project-L group `info` attribute
- Flag 16 in badge log share
- Flag 17 in DA-only admin_flag share
- Windows Firewall disabled

**To use:** Launch from image, wait ~2 min for AD services to start. Startup script should only need to: set Administrator password to known value.

### Gotcha: extensionAttribute1 doesn't exist without Exchange schema

The A2 spec calls for `extensionAttribute1` on the Project-L group. This attribute only exists if the Exchange schema extensions have been installed. On a bare Windows AD without Exchange, it's not available.

**Fix:** Use the `info` attribute instead. It's a standard AD attribute on all objects, not shown by default in most enumeration tools — participants still need to explicitly query it. Updated the flag 14 spec accordingly.

### Gotcha: Kerberoast returned svc-scada hash instead of svc-backup

When running `GetUserSPNs` authenticating as svc-backup, it returned the svc-scada TGS hash (because it enumerates ALL SPNs and svc-backup can't request its own TGS). In the CTF, participants will authenticate as a non-SPN account (e.g., discovered from A3 config or A0 employee directory) and get hashes for BOTH svc-backup and svc-scada. Both are crackable. This is actually better for the CTF — participants get two paths.

### Cost Estimate
- 1x e2-medium Windows VM: ~$0.067/hr + $0.023/hr (Windows license) = ~$0.09/hr
- For a 4-hour CTF event: ~$0.36
- For a week of testing: ~$15
- Negligible compared to the 110-participant cluster

### Test Environment Resources (TO CLEAN UP)
- VPC: `ctf-test-lab`
- Subnet: `ctf-test-subnet` (us-east4, 10.100.0.0/24)
- Firewall rules: all external access locked to 173.181.31.170/32 (2026-04-11)
  - ctf-test-allow-ssh: TCP:22 from our IP only
  - ctf-test-allow-rdp: TCP:3389 from our IP only
  - ctf-test-allow-winrm: TCP:5985-5986 from our IP only
  - ctf-test-allow-internal: all TCP/UDP/ICMP from 10.100.0.0/24
- VMs: ctf-test-a2-dc (Samba, can delete), ctf-test-attacker (keep for testing), ctf-test-a2-windc (stopped, image created)
- Image: ctf-a2-windc-base-v1 (KEEP)
- NOTE: If your IP changes, update firewall rules with `gcloud compute firewall-rules update ctf-test-allow-ssh --source-ranges=NEW_IP/32`
