"""Secret-safe setup plans for bounded ACES Active Directory realization."""

from __future__ import annotations

import base64

from .base import SetupStep

_READ_VALUE = r"""
function Read-AcesValue {
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
$DnsName = Read-AcesValue
$NetbiosName = Read-AcesValue
$AuthorityUsername = Read-AcesValue
$DsrmPasswordText = Read-AcesValue
$AuthorityPasswordText = Read-AcesValue
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
        Write-Output "ACES_AD_PROMOTION_VERIFIED"
        exit 0
    }
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
    Write-Output "ACES_AD_PROMOTION_APPLIED"
    exit 0
} catch { Write-Error "ACES_AD_PROMOTION_FAILED"; exit 1 }
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
$DnsName = Read-AcesValue
$NetbiosName = Read-AcesValue
$Username = Read-AcesValue
$PasswordText = Read-AcesValue
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
    Write-Output "ACES_AD_AUTHORITY_VERIFIED"
    exit 0
} catch { Write-Error "ACES_AD_AUTHORITY_FAILED"; exit 1 }
finally { $PasswordText = $null; $Password = $null }
"""
)

_VERIFY_CONTROLLER = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-AcesValue
$NetbiosName = Read-AcesValue
try {
    $domain = Get-ADDomain -ErrorAction Stop
    $controller = Get-ADDomainController -Identity $env:COMPUTERNAME -ErrorAction Stop
    if ($controller.Name -ine $env:COMPUTERNAME -or $controller.Domain -ine $DnsName `
        -or $domain.DNSRoot -cne $DnsName -or $domain.NetBIOSName -cne $NetbiosName) { exit 1 }
    Write-Output "ACES_AD_CONTROLLER_READBACK_VERIFIED"
    exit 0
} catch { Write-Error "ACES_AD_CONTROLLER_READBACK_FAILED"; exit 1 }
"""
)

_MEMBER_STATE = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-AcesValue
$ControllerIp = Read-AcesValue
try {
    Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
        Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses $ControllerIp -ErrorAction Stop
    }
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $machine = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($env:COMPUTERNAME))
    if ($computer.PartOfDomain) {
        if ($computer.Domain -cne $DnsName) { exit 1 }
        Write-Output "ACES_AD_MEMBER_ALREADY_JOINED:$machine"
        exit 0
    }
    Write-Output "ACES_AD_MEMBER_JOIN_REQUIRED:$machine"
    exit 0
} catch { Write-Error "ACES_AD_MEMBER_STATE_FAILED"; exit 1 }
"""
)

_PROVISION_OFFLINE_JOIN = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-AcesValue
$MachineName = Read-AcesValue
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
} catch { Write-Error "ACES_AD_OFFLINE_JOIN_PROVISION_FAILED"; exit 1 }
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
$DnsName = Read-AcesValue
$ControllerIp = Read-AcesValue
$OfflineJoinBlob = Read-AcesValue
$BlobPath = Join-Path $env:TEMP ([IO.Path]::GetRandomFileName())
try {
    Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
        Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses $ControllerIp -ErrorAction Stop
    }
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    if ($computer.PartOfDomain) {
        if ($computer.Domain -cne $DnsName) { exit 1 }
        Write-Output "ACES_AD_MEMBER_ALREADY_JOINED"
        exit 0
    }
    [IO.File]::WriteAllBytes($BlobPath, [Convert]::FromBase64String($OfflineJoinBlob))
    $OfflineJoinBlob = $null
    & djoin.exe /requestODJ /loadfile $BlobPath /windowspath $env:SystemRoot /localos | Out-Null
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Write-Output "ACES_AD_MEMBER_JOIN_APPLIED"
    exit 0
} catch { Write-Error "ACES_AD_MEMBER_JOIN_FAILED"; exit 1 }
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
$DnsName = Read-AcesValue
try {
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    if (-not $computer.PartOfDomain -or $computer.Domain -cne $DnsName) { exit 1 }
    Write-Output "ACES_AD_MEMBER_READBACK_VERIFIED"
    exit 0
} catch { Write-Error "ACES_AD_MEMBER_READBACK_FAILED"; exit 1 }
"""
)

_REALIZE_ACCOUNT = (
    _READ_VALUE
    + r"""
$ErrorActionPreference = "Stop"
$DnsName = Read-AcesValue
$Username = Read-AcesValue
$PasswordText = Read-AcesValue
$Spn = Read-AcesValue
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
    Write-Output "ACES_AD_ACCOUNT_READBACK_VERIFIED"
    exit 0
} catch { Write-Error "ACES_AD_ACCOUNT_SPN_FAILED"; exit 1 }
finally { $PasswordText = $null; $Password = $null }
"""
)


def _b64(value: str) -> str:
    """Encode one UTF-8 runtime value for line-oriented PowerShell stdin."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _context(**values: str) -> dict[str, str]:
    """Return raw and base64 forms for each setup-plan runtime value."""
    context = dict(values)
    context.update({f"{key}_b64": _b64(value) for key, value in values.items()})
    return context


class AcesDomainControllerPlan:
    """Prepare the RID-500 authority and promote one exact authored domain."""

    def __init__(
        self, *, dns_name: str, netbios_name: str, authority_username: str, dsrm_password: str, authority_password: str
    ) -> None:
        self._context = _context(
            dns_name=dns_name,
            netbios_name=netbios_name,
            authority_username=authority_username,
            dsrm_password=dsrm_password,
            authority_password=authority_password,
        )

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="aces_ad_promote",
                script=_PROMOTE,
                stdin_input=(
                    "{{ dns_name_b64 }}\n{{ netbios_name_b64 }}\n{{ authority_username_b64 }}\n"
                    "{{ dsrm_password_b64 }}\n{{ authority_password_b64 }}\n"
                ),
                timeout_seconds=1200,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "netbios_name": self._context["netbios_name"],
            "netbios_name_b64": self._context["netbios_name_b64"],
            "authority_username": self._context["authority_username"],
            "authority_username_b64": self._context["authority_username_b64"],
            "dsrm_password": self._context["dsrm_password"],
            "dsrm_password_b64": self._context["dsrm_password_b64"],
            "authority_password": self._context["authority_password"],
            "authority_password_b64": self._context["authority_password_b64"],
        }


class AcesDomainControllerVerificationPlan:
    """Reconcile and read back the domain authority after promotion/reconnect."""

    def __init__(self, *, dns_name: str, netbios_name: str, authority_username: str, authority_password: str) -> None:
        self._context = _context(
            dns_name=dns_name,
            netbios_name=netbios_name,
            authority_username=authority_username,
            authority_password=authority_password,
        )

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="aces_ad_authority",
                script=_AUTHORITY,
                stdin_input=(
                    "{{ dns_name_b64 }}\n{{ netbios_name_b64 }}\n{{ authority_username_b64 }}\n"
                    "{{ authority_password_b64 }}\n"
                ),
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        return SetupStep(
            name="aces_ad_verify_controller",
            script=_VERIFY_CONTROLLER,
            stdin_input="{{ dns_name_b64 }}\n{{ netbios_name_b64 }}\n",
            timeout_seconds=600,
            is_verification=True,
        )

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "netbios_name": self._context["netbios_name"],
            "netbios_name_b64": self._context["netbios_name_b64"],
            "authority_username": self._context["authority_username"],
            "authority_username_b64": self._context["authority_username_b64"],
            "authority_password": self._context["authority_password"],
            "authority_password_b64": self._context["authority_password_b64"],
        }


class AcesDomainMemberStatePlan:
    """Read the exact local machine identity and current domain membership."""

    def __init__(self, *, dns_name: str, controller_ip: str) -> None:
        self._context = _context(dns_name=dns_name, controller_ip=controller_ip)

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="aces_ad_member_state",
                script=_MEMBER_STATE,
                stdin_input="{{ dns_name_b64 }}\n{{ controller_ip_b64 }}\n",
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "controller_ip": self._context["controller_ip"],
            "controller_ip_b64": self._context["controller_ip_b64"],
        }


class AcesDomainOfflineJoinProvisionPlan:
    """Create one machine-scoped offline-domain-join package on the controller."""

    def __init__(self, *, dns_name: str, machine_name: str) -> None:
        self._context = _context(dns_name=dns_name, machine_name=machine_name)

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="aces_ad_offline_join_provision",
                script=_PROVISION_OFFLINE_JOIN,
                stdin_input=(f"{self._context['dns_name_b64']}\n{self._context['machine_name_b64']}\n"),
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "machine_name": self._context["machine_name"],
            "machine_name_b64": self._context["machine_name_b64"],
        }


class AcesDomainMemberPlan:
    """Apply a machine-scoped offline-domain-join package to one member."""

    def __init__(self, *, dns_name: str, controller_ip: str, offline_join_blob: str) -> None:
        self._context = _context(
            dns_name=dns_name,
            controller_ip=controller_ip,
            offline_join_blob_secret=offline_join_blob,
        )

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="aces_ad_join_member",
                script=_JOIN_MEMBER,
                stdin_input=("{{ dns_name_b64 }}\n{{ controller_ip_b64 }}\n{{ offline_join_blob_secret_b64 }}\n"),
                timeout_seconds=1200,
                requires_reboot=True,
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        return SetupStep(
            name="aces_ad_verify_member",
            script=_VERIFY_MEMBER,
            stdin_input="{{ dns_name_b64 }}\n",
            timeout_seconds=600,
            is_verification=True,
        )

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "controller_ip": self._context["controller_ip"],
            "controller_ip_b64": self._context["controller_ip_b64"],
            "offline_join_blob_secret": self._context["offline_join_blob_secret"],
            "offline_join_blob_secret_b64": self._context["offline_join_blob_secret_b64"],
        }


class AcesDomainAccountPlan:
    """Reconcile one domain principal, register its SPN uniquely, and read it back."""

    def __init__(self, *, dns_name: str, username: str, password: str, spn: str | None) -> None:
        self._context = _context(dns_name=dns_name, username=username, password=password, spn=spn or "")

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name="aces_ad_account_spn",
                script=_REALIZE_ACCOUNT,
                stdin_input="{{ dns_name_b64 }}\n{{ username_b64 }}\n{{ password_b64 }}\n{{ spn_b64 }}\n",
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> None:
        return None

    def get_context(self, _instance: object) -> dict[str, str]:
        return {
            "dns_name": self._context["dns_name"],
            "dns_name_b64": self._context["dns_name_b64"],
            "username": self._context["username"],
            "username_b64": self._context["username_b64"],
            "password": self._context["password"],
            "password_b64": self._context["password_b64"],
            "spn": self._context["spn"],
            "spn_b64": self._context["spn_b64"],
        }
