# POLARIS A2 post-promotion setup — runs via SSM Run Command AFTER the DC
# has rebooted out of Install-ADDSForest and AD DS is serving.
#
# Creates the OUs, users, groups, SPNs, DCSync ACL, Project-L info flag,
# badgelogs share, and admin_flag share that flags 14/16/17 require.
#
# Idempotent: re-runs should be safe and report what was already in place.

[CmdletBinding()]
param(
    [string]$AdminPassword = "CortexSavesTheDay!"
)

$ErrorActionPreference = "Stop"
$LogFile = "C:\polaris-a2-setup.log"
Start-Transcript -Path $LogFile -Append

Write-Host "=== POLARIS A2 setup $(Get-Date -Format o) ==="

# Wait until AD Web Services / NTDS are up.
for ($i = 0; $i -lt 60; $i++) {
    try {
        Get-ADDomain -ErrorAction Stop | Out-Null
        break
    } catch {
        Write-Host "Waiting for AD DS ($i)..."
        Start-Sleep -Seconds 5
    }
}

Import-Module ActiveDirectory

$DomainDn = (Get-ADDomain).DistinguishedName
Write-Host "Domain DN: $DomainDn"

# -----------------------------------------------------------------------
# Phase 1 — Organizational units (matches design doc A2-domain-controller.md)
# -----------------------------------------------------------------------
$OuNames = @("Consulting", "Engineering", "Security", "Executive", "ServiceAccounts", "Disabled")
foreach ($ou in $OuNames) {
    $ouDn = "OU=$ou,$DomainDn"
    if (-not (Get-ADOrganizationalUnit -Filter "DistinguishedName -eq '$ouDn'" -ErrorAction SilentlyContinue)) {
        New-ADOrganizationalUnit -Name $ou -Path $DomainDn -ProtectedFromAccidentalDeletion $false
        Write-Host "  OU created: $ou"
    } else {
        Write-Host "  OU already exists: $ou"
    }
}

# -----------------------------------------------------------------------
# Phase 2 — Users. Each tuple: sam, displayName, givenName, sn, ou, password
# Passwords match the values the walkthroughs and smoketest hard-code.
# -----------------------------------------------------------------------
$Users = @(
    @{ sam = "v.harlan";     dn = "Vincent Harlan";   give = "Vincent"; sn = "Harlan";   ou = "Executive";       pass = "Boreas2025!" },
    @{ sam = "m.webb";       dn = "Marcus Webb";      give = "Marcus";  sn = "Webb";     ou = "Executive";       pass = "Welcome1" },
    @{ sam = "e.vasik";      dn = "Elena Vasik";      give = "Elena";   sn = "Vasik";    ou = "Engineering";     pass = "Reactor#Core9" },
    @{ sam = "r.tanaka";     dn = "Rio Tanaka";       give = "Rio";     sn = "Tanaka";   ou = "Engineering";     pass = "SimEngine#42" },
    @{ sam = "p.nielsen";    dn = "Paul Nielsen";     give = "Paul";    sn = "Nielsen";  ou = "Engineering";     pass = "Hydraulics1" },
    @{ sam = "k.yamamoto";   dn = "Kenji Yamamoto";   give = "Kenji";   sn = "Yamamoto"; ou = "Engineering";     pass = "Sensor2025" },
    @{ sam = "f.okoye";      dn = "Folake Okoye";     give = "Folake";  sn = "Okoye";    ou = "Engineering";     pass = "AIModel2025" },
    @{ sam = "d.kowalski";   dn = "Daniel Kowalski";  give = "Daniel";  sn = "Kowalski"; ou = "Engineering";     pass = "P@ssw0rd123" },
    @{ sam = "s.morrison";   dn = "Sarah Morrison";   give = "Sarah";   sn = "Morrison"; ou = "Security";        pass = "Br3ach!ng" },
    @{ sam = "guard.petrov"; dn = "Ivan Petrov";      give = "Ivan";    sn = "Petrov";   ou = "Security";        pass = "PatrolBeat!" },
    @{ sam = "s.ivanov";     dn = "Sergei Ivanov";    give = "Sergei";  sn = "Ivanov";   ou = "Consulting";      pass = "Welcome1" },
    @{ sam = "p.shah";       dn = "Priya Shah";       give = "Priya";   sn = "Shah";     ou = "Consulting";      pass = "Welcome1" },
    @{ sam = "j.chen";       dn = "James Chen";       give = "James";   sn = "Chen";     ou = "Disabled";        pass = "Summer2024" },
    @{ sam = "svc-backup";   dn = "SVC Backup";       give = "SVC";     sn = "Backup";   ou = "ServiceAccounts"; pass = "Password1" },
    @{ sam = "svc-scada";    dn = "SVC SCADA";        give = "SVC";     sn = "SCADA";    ou = "ServiceAccounts"; pass = "Sc@da#2025!" }
)

foreach ($u in $Users) {
    $sam = $u.sam
    $ouDn = "OU=$($u.ou),$DomainDn"
    $secure = ConvertTo-SecureString $u.pass -AsPlainText -Force

    $existing = Get-ADUser -Filter "sAMAccountName -eq '$sam'" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  user exists: $sam"
        Set-ADAccountPassword -Identity $sam -Reset -NewPassword $secure
        Set-ADUser -Identity $sam -Enabled $true -PasswordNeverExpires $true
        # Move into correct OU if misplaced.
        if ($existing.DistinguishedName -notlike "*,$ouDn") {
            Move-ADObject -Identity $existing.DistinguishedName -TargetPath $ouDn
        }
    } else {
        New-ADUser `
            -Name $u.dn `
            -GivenName $u.give `
            -Surname $u.sn `
            -SamAccountName $sam `
            -UserPrincipalName "$sam@boreas.local" `
            -Path $ouDn `
            -AccountPassword $secure `
            -Enabled $true `
            -PasswordNeverExpires $true `
            -ChangePasswordAtLogon $false
        Write-Host "  user created: $sam in $($u.ou)"
    }
}

# j.chen should be DISABLED but still in Engineering group membership per design.
Disable-ADAccount -Identity "j.chen"

# -----------------------------------------------------------------------
# Phase 3 — Groups, including the nested Engineering-Support > Research-
# Coordination > Project-L chain that flag 14 requires the participant to
# unwrap.
# -----------------------------------------------------------------------
$Groups = @(
    @{ name = "Lab-Access";             scope = "Global" },
    @{ name = "Project-L";              scope = "Global" },
    @{ name = "Research-Coordination";  scope = "Global" },
    @{ name = "Engineering-Support";    scope = "Global" },
    @{ name = "SCADA-Admins";           scope = "Global" },
    @{ name = "Security-Staff";         scope = "Global" }
)

foreach ($g in $Groups) {
    if (-not (Get-ADGroup -Filter "Name -eq '$($g.name)'" -ErrorAction SilentlyContinue)) {
        New-ADGroup -Name $g.name -SamAccountName $g.name -GroupCategory Security -GroupScope $g.scope -Path $DomainDn
        Write-Host "  group created: $($g.name)"
    } else {
        Write-Host "  group exists:  $($g.name)"
    }
}

function Add-GroupMemberIdempotent {
    param([string]$Group, [string[]]$Members)
    foreach ($m in $Members) {
        try {
            Add-ADGroupMember -Identity $Group -Members $m -ErrorAction Stop
            Write-Host "    $Group + $m"
        } catch {
            if ($_.Exception.Message -match "already a member") {
                Write-Host "    $Group already has $m"
            } else {
                throw
            }
        }
    }
}

Add-GroupMemberIdempotent -Group "Lab-Access"            -Members @("e.vasik","r.tanaka","p.nielsen","k.yamamoto","f.okoye")
Add-GroupMemberIdempotent -Group "Project-L"             -Members @("e.vasik","m.webb")
Add-GroupMemberIdempotent -Group "Research-Coordination" -Members @("Project-L")
Add-GroupMemberIdempotent -Group "Engineering-Support"   -Members @("Research-Coordination")
Add-GroupMemberIdempotent -Group "SCADA-Admins"          -Members @("svc-scada","d.kowalski")
Add-GroupMemberIdempotent -Group "Security-Staff"        -Members @("s.morrison","guard.petrov")
Add-GroupMemberIdempotent -Group "Domain Admins"         -Members @("v.harlan")
Add-GroupMemberIdempotent -Group "Backup Operators"      -Members @("svc-backup")

# -----------------------------------------------------------------------
# Phase 4 — SPNs + encryption types.
# svc-backup and svc-scada need Kerberoastable SPNs. msDS-SupportedEncryptionTypes
# set to include RC4_HMAC_MD5 (bit 4) so Kerberoast returns $krb5tgs$23$ hashes
# that hashcat -m 13100 / john's krb5tgs format can crack.
# -----------------------------------------------------------------------
$ServicePrincipalNames = @{
    "svc-backup" = @("MSSQLSvc/fileserv.boreas.local:1433","MSSQLSvc/fileserv.boreas.local")
    "svc-scada"  = @("HTTP/scada-gw.boreas.local")
}

foreach ($svc in $ServicePrincipalNames.Keys) {
    $userObj = Get-ADUser -Identity $svc -Properties servicePrincipalName,msDS-SupportedEncryptionTypes
    foreach ($spn in $ServicePrincipalNames[$svc]) {
        if ($userObj.servicePrincipalName -notcontains $spn) {
            Set-ADUser -Identity $svc -Add @{ servicePrincipalName = $spn }
            Write-Host "  $svc + SPN $spn"
        }
    }
    # 0x04 = RC4_HMAC_MD5 only. The walkthrough Kerberoast step cracks the
    # TGS with `hashcat -m 13100` / john's krb5tgs format, both of which
    # target etype 23 (RC4). If AES128 or AES256 is in the supported set,
    # modern KDCs return the strongest common etype (usually $krb5tgs$18$
    # AES256) which needs `-m 19700` instead. Pinning to RC4 keeps the
    # attack chain the walkthrough documents working out of the box.
    Set-ADUser -Identity $svc -Replace @{ "msDS-SupportedEncryptionTypes" = 4 }
}

# -----------------------------------------------------------------------
# Phase 5 — DCSync ACL on svc-backup.
# The walkthrough chain is Kerberoast -> crack -> secretsdump -just-dc-user.
# secretsdump uses DRSUAPI Replication rights, which require both
# "Replicating Directory Changes" and "Replicating Directory Changes All"
# on the domain root DN.
# -----------------------------------------------------------------------
$backupUser = Get-ADUser svc-backup
$backupSid  = $backupUser.SID
$rootDn     = "AD:$DomainDn"
$acl        = Get-Acl $rootDn

$ReplChanges    = [GUID]"1131f6aa-9c07-11d1-f79f-00c04fc2dcd2"
$ReplChangesAll = [GUID]"1131f6ad-9c07-11d1-f79f-00c04fc2dcd2"

$needed = @($ReplChanges,$ReplChangesAll)
foreach ($guid in $needed) {
    $already = $acl.Access | Where-Object {
        $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $backupSid.Value -and
        $_.ObjectType -eq $guid
    }
    if (-not $already) {
        $ace = New-Object System.DirectoryServices.ActiveDirectoryAccessRule(
            $backupSid,
            [System.DirectoryServices.ActiveDirectoryRights]::ExtendedRight,
            [System.Security.AccessControl.AccessControlType]::Allow,
            $guid
        )
        $acl.AddAccessRule($ace)
    }
}
Set-Acl -Path $rootDn -AclObject $acl
Write-Host "  svc-backup DCSync ACL set"

# -----------------------------------------------------------------------
# Phase 6 — Flag 14: Project-L.info attribute.
# The walkthrough says the participant enumerates nested groups, finds
# Project-L, then queries the `info` attribute. Set that here.
# -----------------------------------------------------------------------
Set-ADGroup -Identity "Project-L" -Replace @{ info = "FLAG{2f8b4a6c1d9e7053}" }
Write-Host "  Project-L info attribute set"

# -----------------------------------------------------------------------
# Phase 7 — Flag 16: badgelogs share with Petrov anomaly CSV.
# Share is readable by Domain Users (broad). CSV is drafted inline rather
# than COPYed from the content dir because we want to control the row
# format used by the smoketest grep.
# -----------------------------------------------------------------------
$badgeRoot = "C:\Shares\badgelogs"
New-Item -ItemType Directory -Path $badgeRoot -Force | Out-Null

$csv = @"
timestamp,badge_id,name,location,action,comment
2026-03-01T07:58,B-0017,Ivan Petrov,Main Entrance,IN,"Scheduled 08:00-16:00 shift"
2026-03-01T15:59,B-0017,Ivan Petrov,Main Entrance,OUT,"End of scheduled shift"
2026-03-02T07:55,B-0017,Ivan Petrov,Main Entrance,IN,"Scheduled 08:00-16:00 shift"
2026-03-02T16:02,B-0017,Ivan Petrov,Main Entrance,OUT,"End of scheduled shift"
2026-03-05T02:11,B-0017,Ivan Petrov,Underground Hatch,IN,"Off-schedule access - no other guards on duty"
2026-03-05T02:58,B-0017,Ivan Petrov,(no activity 47min),-,"Badge goes silent - see 03:45 entry"
2026-03-05T03:45,B-0017,Ivan Petrov,Parking Lot C Exit,OUT,"FLAG{b3d7e1f0c8a24596}"
2026-03-12T02:18,B-0017,Ivan Petrov,Underground Hatch,IN,"Off-schedule access"
2026-03-12T02:55,B-0017,Ivan Petrov,Parking Lot C Exit,OUT,""
2026-03-18T02:04,B-0017,Ivan Petrov,Underground Hatch,IN,"Off-schedule access"
2026-03-18T03:02,B-0017,Ivan Petrov,Parking Lot C Exit,OUT,""
2026-03-21T02:22,B-0017,Ivan Petrov,Underground Hatch,IN,"Off-schedule access"
2026-03-21T03:11,B-0017,Ivan Petrov,Parking Lot C Exit,OUT,""
2026-03-25T02:14,B-0017,Ivan Petrov,Underground Hatch,IN,"Off-schedule access"
2026-03-25T02:49,B-0017,Ivan Petrov,Parking Lot C Exit,OUT,""
2026-03-28T02:31,B-0017,Ivan Petrov,Underground Hatch,IN,"Off-schedule access"
2026-03-28T03:19,B-0017,Ivan Petrov,Parking Lot C Exit,OUT,""
2026-03-02T08:05,B-0019,Sarah Morrison,Main Entrance,IN,"Scheduled 08:00-16:00"
2026-03-02T16:01,B-0019,Sarah Morrison,Main Entrance,OUT,""
2026-03-05T08:02,B-0021,Jenna Watts,Main Entrance,IN,"Scheduled 08:00-16:00"
2026-03-05T16:00,B-0021,Jenna Watts,Main Entrance,OUT,""
"@
Set-Content -Path "$badgeRoot\access_log_march_2026.csv" -Value $csv -Encoding UTF8

if (-not (Get-SmbShare -Name "badgelogs" -ErrorAction SilentlyContinue)) {
    New-SmbShare -Name "badgelogs" -Path $badgeRoot -FullAccess "BUILTIN\Administrators" -ChangeAccess "BOREAS\Domain Users"
    Write-Host "  badgelogs share created"
} else {
    Write-Host "  badgelogs share already exists"
}

# -----------------------------------------------------------------------
# Phase 8 — Flag 17: admin_flag share. DA-only NTFS ACL + share ACL.
# -----------------------------------------------------------------------
$adminFlagRoot = "C:\Shares\admin_flag"
New-Item -ItemType Directory -Path $adminFlagRoot -Force | Out-Null
Set-Content -Path "$adminFlagRoot\flag.txt" -Value "FLAG{6c0a9d4e7f2b8135}" -Encoding UTF8

# NTFS: disable inheritance and strip non-admin ACEs.
$ntfs = Get-Acl $adminFlagRoot
$ntfs.SetAccessRuleProtection($true, $false)
foreach ($rule in $ntfs.Access) { $ntfs.RemoveAccessRule($rule) | Out-Null }
$adminsAllow = New-Object System.Security.AccessControl.FileSystemAccessRule(
    (New-Object System.Security.Principal.NTAccount("BUILTIN\Administrators")),
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$ntfs.AddAccessRule($adminsAllow)
Set-Acl $adminFlagRoot $ntfs

if (-not (Get-SmbShare -Name "admin_flag" -ErrorAction SilentlyContinue)) {
    New-SmbShare -Name "admin_flag" -Path $adminFlagRoot -FullAccess "BOREAS\Domain Admins"
    Write-Host "  admin_flag share created (DA only)"
} else {
    Write-Host "  admin_flag share already exists"
}

# -----------------------------------------------------------------------
# Phase 9 — Force a fresh Administrator password using the one the operator
# holds in Secrets Manager so the flag 17 pass-the-hash chain yields a hash
# we can predict.
# -----------------------------------------------------------------------
Set-ADAccountPassword -Identity "Administrator" -Reset -NewPassword (ConvertTo-SecureString $AdminPassword -AsPlainText -Force)
Set-ADUser -Identity "Administrator" -PasswordNeverExpires $true

# -----------------------------------------------------------------------
# Sanity check
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "=== Verification ==="
Get-ADUser -Filter * -SearchBase $DomainDn | Select-Object sAMAccountName,Enabled | Sort-Object sAMAccountName | Format-Table -AutoSize
Write-Host ""
Write-Host "Project-L members (direct + nested):"
Get-ADGroupMember -Identity "Project-L" -Recursive | Format-Table sAMAccountName
Write-Host ""
Write-Host "Project-L info attribute:"
(Get-ADGroup "Project-L" -Properties info).info
Write-Host ""
Write-Host "SPNs:"
Get-ADUser -Filter "sAMAccountName -like 'svc-*'" -Properties servicePrincipalName | Format-Table sAMAccountName,servicePrincipalName
Write-Host ""
Write-Host "Shares:"
Get-SmbShare | Where-Object { $_.Name -in @("badgelogs","admin_flag") } | Format-Table Name,Path
Write-Host ""
Write-Host "=== POLARIS A2 setup complete ==="

Stop-Transcript
