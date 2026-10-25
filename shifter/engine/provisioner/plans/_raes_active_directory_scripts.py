"""PowerShell sources for the bounded RAES Active Directory setup plans."""

from __future__ import annotations

_READ_VALUE = r"""
function Read-RaesValue {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { exit 1 }
    try { return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line)) }
    catch { exit 1 }
}
"""

_PROMOTE = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$NetbiosName = Read-RaesValue
$AuthorityUsername = Read-RaesValue
$DsrmPasswordText = Read-RaesValue
$AuthorityPasswordText = Read-RaesValue
$RequireExistingDomain = Read-RaesValue
try {
    $existing = $null
    if (Get-Command Get-ADDomain -ErrorAction SilentlyContinue) {
        $existing = Get-ADDomain -ErrorAction SilentlyContinue
    }
    if ($existing) {
        $localController = Get-ADDomainController -Identity $env:COMPUTERNAME -ErrorAction SilentlyContinue
        if (-not $localController -or $localController.Name -ine $env:COMPUTERNAME `
            -or $localController.Domain -ine $DnsName -or $existing.DNSRoot -cne $DnsName `
            -or $existing.NetBIOSName -cne $NetbiosName) { exit 1 }
        Write-Output "RAES_AD_PROMOTION_VERIFIED"
        exit 0
    }
    # A prepromoted image must already be this domain's controller; never
    # create a fresh forest in its place.
    if ($RequireExistingDomain -ceq "1") { exit 1 }
    $feature = Get-WindowsFeature -Name AD-Domain-Services
    if (-not $feature.Installed) {
        Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools -ErrorAction Stop | Out-Null
    }
    $localAuthority = Get-LocalUser | Where-Object { $_.SID.Value.EndsWith("-500") }
    if (-not $localAuthority -or $localAuthority.Name -cne $AuthorityUsername) { exit 1 }
    $AuthorityPassword = ConvertTo-SecureString $AuthorityPasswordText -AsPlainText -Force
    $AuthorityPasswordText = $null
    Set-LocalUser -InputObject $localAuthority -Password $AuthorityPassword -ErrorAction Stop
    Enable-LocalUser -InputObject $localAuthority -ErrorAction Stop
    $DsrmPassword = ConvertTo-SecureString $DsrmPasswordText -AsPlainText -Force
    $DsrmPasswordText = $null
    Install-ADDSForest -DomainName $DnsName -DomainNetbiosName $NetbiosName `
        -SafeModeAdministratorPassword $DsrmPassword -InstallDns -NoRebootOnCompletion -Force -ErrorAction Stop
    Write-Output "RAES_AD_PROMOTION_APPLIED"
    exit 0
} catch { Write-Error "RAES_AD_PROMOTION_FAILED"; exit 1 }
finally {
    $DsrmPasswordText = $null
    $DsrmPassword = $null
    $AuthorityPasswordText = $null
    $AuthorityPassword = $null
}
"""
)

_AUTHORITY = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$NetbiosName = Read-RaesValue
$Username = Read-RaesValue
$PasswordText = Read-RaesValue
try {
    $domain = Get-ADDomain -ErrorAction Stop
    if ($domain.DNSRoot -cne $DnsName -or $domain.NetBIOSName -cne $NetbiosName) { exit 1 }
    $authority = Get-ADUser -Identity $Username -Properties SID,Enabled -ErrorAction Stop
    if (-not $authority.SID.Value.EndsWith("-500")) { exit 1 }
    $Password = ConvertTo-SecureString $PasswordText -AsPlainText -Force
    $PasswordText = $null
    Set-ADAccountPassword -Identity $authority -Reset -NewPassword $Password -ErrorAction Stop
    Enable-ADAccount -Identity $authority -ErrorAction Stop
    $verified = Get-ADUser -Identity $Username -Properties SID,Enabled -ErrorAction Stop
    if (-not $verified.Enabled -or -not $verified.SID.Value.EndsWith("-500")) { exit 1 }
    Write-Output "RAES_AD_AUTHORITY_VERIFIED"
    exit 0
} catch { Write-Error "RAES_AD_AUTHORITY_FAILED"; exit 1 }
finally { $PasswordText = $null; $Password = $null }
"""
)

_VERIFY_CONTROLLER = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$NetbiosName = Read-RaesValue
try {
    $domain = Get-ADDomain -ErrorAction Stop
    $controller = Get-ADDomainController -Identity $env:COMPUTERNAME -ErrorAction Stop
    if ($controller.Name -ine $env:COMPUTERNAME -or $controller.Domain -ine $DnsName `
        -or $domain.DNSRoot -cne $DnsName -or $domain.NetBIOSName -cne $NetbiosName) { exit 1 }
    Write-Output "RAES_AD_CONTROLLER_READBACK_VERIFIED"
    exit 0
} catch { Write-Error "RAES_AD_CONTROLLER_READBACK_FAILED"; exit 1 }
"""
)

_MEMBER_STATE = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$ControllerIp = Read-RaesValue
try {
    Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
        Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses $ControllerIp -ErrorAction Stop
    }
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $machine = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($env:COMPUTERNAME))
    if ($computer.PartOfDomain) {
        if ($computer.Domain -cne $DnsName) { exit 1 }
        Write-Output "RAES_AD_MEMBER_ALREADY_JOINED:$machine"
        exit 0
    }
    Write-Output "RAES_AD_MEMBER_JOIN_REQUIRED:$machine"
    exit 0
} catch { Write-Error "RAES_AD_MEMBER_STATE_FAILED"; exit 1 }
"""
)

_PROVISION_OFFLINE_JOIN = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$MachineName = Read-RaesValue
$BlobPath = Join-Path $env:TEMP ([IO.Path]::GetRandomFileName())
try {
    $domain = Get-ADDomain -ErrorAction Stop
    if ($domain.DNSRoot -cne $DnsName) { exit 1 }
    if ($MachineName -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,14}$') { exit 1 }
    & djoin.exe /provision /domain $DnsName /machine $MachineName /savefile $BlobPath /reuse | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $BlobPath)) { exit 1 }
    $bytes = [IO.File]::ReadAllBytes($BlobPath)
    if ($bytes.Length -eq 0) { exit 1 }
    [Console]::Out.WriteLine([Convert]::ToBase64String($bytes))
    exit 0
} catch { Write-Error "RAES_AD_OFFLINE_JOIN_PROVISION_FAILED"; exit 1 }
finally {
    if (Test-Path -LiteralPath $BlobPath) { Remove-Item -LiteralPath $BlobPath -Force -ErrorAction SilentlyContinue }
    $bytes = $null
}
"""
)

_JOIN_MEMBER = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$ControllerIp = Read-RaesValue
$OfflineJoinBlob = Read-RaesValue
$BlobPath = Join-Path $env:TEMP ([IO.Path]::GetRandomFileName())
try {
    Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
        Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses $ControllerIp -ErrorAction Stop
    }
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    if ($computer.PartOfDomain) {
        if ($computer.Domain -cne $DnsName) { exit 1 }
        Write-Output "RAES_AD_MEMBER_ALREADY_JOINED"
        exit 0
    }
    [IO.File]::WriteAllBytes($BlobPath, [Convert]::FromBase64String($OfflineJoinBlob))
    $OfflineJoinBlob = $null
    & djoin.exe /requestODJ /loadfile $BlobPath /windowspath $env:SystemRoot /localos | Out-Null
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Write-Output "RAES_AD_MEMBER_JOIN_APPLIED"
    exit 0
} catch { Write-Error "RAES_AD_MEMBER_JOIN_FAILED"; exit 1 }
finally {
    if (Test-Path -LiteralPath $BlobPath) { Remove-Item -LiteralPath $BlobPath -Force -ErrorAction SilentlyContinue }
    $OfflineJoinBlob = $null
}
"""
)

_VERIFY_MEMBER = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
try {
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    if (-not $computer.PartOfDomain -or $computer.Domain -cne $DnsName) { exit 1 }
    Write-Output "RAES_AD_MEMBER_READBACK_VERIFIED"
    exit 0
} catch { Write-Error "RAES_AD_MEMBER_READBACK_FAILED"; exit 1 }
"""
)

_REALIZE_ACCOUNT = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-RaesValue
$Username = Read-RaesValue
$PasswordText = Read-RaesValue
$Spn = Read-RaesValue
try {
    $domain = Get-ADDomain -ErrorAction Stop
    if ($domain.DNSRoot -cne $DnsName) { exit 1 }
    $Password = ConvertTo-SecureString $PasswordText -AsPlainText -Force
    $PasswordText = $null
    $user = Get-ADUser -Identity $Username -Properties servicePrincipalName,Enabled -ErrorAction SilentlyContinue
    if (-not $user) {
        New-ADUser -Name $Username -SamAccountName $Username -AccountPassword $Password -Enabled $true -ErrorAction Stop
        $user = Get-ADUser -Identity $Username -Properties servicePrincipalName,Enabled -ErrorAction Stop
    } else {
        Set-ADAccountPassword -Identity $user -Reset -NewPassword $Password -ErrorAction Stop
        Enable-ADAccount -Identity $user -ErrorAction Stop
    }
    if ($Spn) {
        $escaped = $Spn.Replace("\", "\5c").Replace("*", "\2a").Replace("(", "\28").Replace(")", "\29")
        $owners = @(Get-ADObject -LDAPFilter "(servicePrincipalName=$escaped)" -Properties servicePrincipalName)
        $ownerConflict = $owners.Count -eq 1 -and `
            $owners[0].DistinguishedName -cne $user.DistinguishedName
        if ($owners.Count -gt 1 -or $ownerConflict) {
            exit 1
        }
        if (-not ($user.servicePrincipalName -ccontains $Spn)) {
            & setspn.exe -S $Spn $Username | Out-Null
            if ($LASTEXITCODE -ne 0) { exit 1 }
        }
    }
    $readback = Get-ADUser -Identity $Username -Properties servicePrincipalName,Enabled -ErrorAction Stop
    if (-not $readback.Enabled) { exit 1 }
    if ($Spn -and -not ($readback.servicePrincipalName -ccontains $Spn)) { exit 1 }
    Write-Output "RAES_AD_ACCOUNT_READBACK_VERIFIED"
    exit 0
} catch { Write-Error "RAES_AD_ACCOUNT_SPN_FAILED"; exit 1 }
finally { $PasswordText = $null; $Password = $null }
"""
)

__all__ = [
    "_AUTHORITY",
    "_JOIN_MEMBER",
    "_MEMBER_STATE",
    "_PROMOTE",
    "_PROVISION_OFFLINE_JOIN",
    "_READ_VALUE",
    "_REALIZE_ACCOUNT",
    "_VERIFY_CONTROLLER",
    "_VERIFY_MEMBER",
]
