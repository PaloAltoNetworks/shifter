"""Install and verify one RAES-authored account's public SSH key (#1560)."""

from __future__ import annotations

import shlex
from typing import Any

from .base import SetupStep

LINUX_SET_AUTHORIZED_KEY_SCRIPT = r"""#!/bin/bash
set -euo pipefail
account_username={{ account_username_quoted }}
if ! id "$account_username" >/dev/null 2>&1; then
    echo "FATAL: authored account is absent" >&2
    exit 1
fi
account_home=$(getent passwd "$account_username" | cut -d: -f6)
account_group=$(id -gn "$account_username")
if [ -z "$account_home" ]; then
    echo "FATAL: authored account has no home directory" >&2
    exit 1
fi
install -d -m 700 -o "$account_username" -g "$account_group" "$account_home/.ssh"
chmod 700 "$account_home/.ssh"
cat > "$account_home/.ssh/authorized_keys" <<'__SHIFTER_RAES_PUBLIC_KEY__'
{{ account_public_key }}
__SHIFTER_RAES_PUBLIC_KEY__
chown "$account_username:$account_group" "$account_home/.ssh/authorized_keys"
chmod 600 "$account_home/.ssh/authorized_keys"
"""

LINUX_VERIFY_AUTHORIZED_KEY_SCRIPT = r"""#!/bin/bash
set -euo pipefail
account_username={{ account_username_quoted }}
account_home=$(getent passwd "$account_username" | cut -d: -f6)
if ! grep -Fqx -- "{{ account_public_key }}" "$account_home/.ssh/authorized_keys"; then
    echo "FATAL: account-specific authorized key is not installed" >&2
    exit 1
fi
test "$(stat -c '%U:%a' "$account_home/.ssh")" = "$account_username:700"
test "$(stat -c '%U:%a' "$account_home/.ssh/authorized_keys")" = "$account_username:600"
echo "Account-specific authorized key installed"
"""

WINDOWS_SET_AUTHORIZED_KEY_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$Username = {{ account_username_quoted }}
$PublicKey = "{{ account_public_key }}"
$User = Get-LocalUser -Name $Username -ErrorAction Stop
$SshDirectory = "C:\Users\$Username\.ssh"
$KeyPath = "C:\Users\$Username\.ssh\authorized_keys"
$ConfigPath = "$env:ProgramData\ssh\sshd_config"
$Sshd = "$env:WINDIR\System32\OpenSSH\sshd.exe"

New-Item -ItemType Directory -Force -Path $SshDirectory | Out-Null
Set-Content -Path $KeyPath -Value $PublicKey -Encoding ascii
$SystemSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$AdministratorsSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
$Inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
    [System.Security.AccessControl.InheritanceFlags]::ObjectInherit

$DirectoryAcl = [System.Security.AccessControl.DirectorySecurity]::new()
$DirectoryAcl.SetAccessRuleProtection($true, $false)
$DirectoryAcl.SetOwner($User.SID)
foreach ($Identity in @($User.SID, $SystemSid, $AdministratorsSid)) {
    $DirectoryAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $Identity,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        $Inheritance,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
}
Set-Acl -Path $SshDirectory -AclObject $DirectoryAcl

$FileAcl = [System.Security.AccessControl.FileSecurity]::new()
$FileAcl.SetAccessRuleProtection($true, $false)
$FileAcl.SetOwner($User.SID)
$FileAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
    $User.SID,
    [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
    [System.Security.AccessControl.AccessControlType]::Allow
))
foreach ($Identity in @($SystemSid, $AdministratorsSid)) {
    $FileAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $Identity,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
}
Set-Acl -Path $KeyPath -AclObject $FileAcl

$StartMarker = "# BEGIN SHIFTER RAES USER $Username"
$EndMarker = "# END SHIFTER RAES USER $Username"
$Content = Get-Content -Raw -Path $ConfigPath
$ExistingBlock = "(?ms)^" + [regex]::Escape($StartMarker) + ".*?^" + [regex]::Escape($EndMarker) + "\r?\n?"
$Content = [regex]::Replace($Content, $ExistingBlock, "")
$Block = @"
$StartMarker
Match User $Username
    AuthorizedKeysFile C:/Users/$Username/.ssh/authorized_keys
$EndMarker
"@
$AdministratorMatch = [regex]::Match($Content, "(?im)^Match\s+Group\s+administrators\s*$")
if ($AdministratorMatch.Success) {
    $Content = $Content.Insert($AdministratorMatch.Index, "$Block`r`n")
} else {
    $Content = $Content.TrimEnd() + "`r`n$Block`r`n"
}
$TempConfigPath = "$ConfigPath.shifter-$PID.tmp"
try {
    Set-Content -Path $TempConfigPath -Value $Content -Encoding ascii
    & $Sshd -t -f $TempConfigPath
    if ($LASTEXITCODE -ne 0) {
        throw "candidate sshd configuration failed validation"
    }
    Move-Item -Force -Path $TempConfigPath -Destination $ConfigPath
} finally {
    if (Test-Path $TempConfigPath) {
        Remove-Item -Force $TempConfigPath
    }
}
Restart-Service -Name sshd -ErrorAction Stop
"""

WINDOWS_VERIFY_AUTHORIZED_KEY_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$Username = {{ account_username_quoted }}
$PublicKey = "{{ account_public_key }}"
$KeyPath = "C:\Users\$Username\.ssh\authorized_keys"
$Sshd = "$env:WINDIR\System32\OpenSSH\sshd.exe"
$InstalledKey = (Get-Content -Raw -Path $KeyPath).Trim()
if ($InstalledKey -ne $PublicKey) {
    Write-Error "FATAL: account-specific authorized key does not match"
    exit 1
}
$User = Get-LocalUser -Name $Username -ErrorAction Stop
$Acl = Get-Acl -Path $KeyPath
if (-not $Acl.AreAccessRulesProtected) {
    Write-Error "FATAL: authorized key ACL still inherits access rules"
    exit 1
}
$ExpectedSids = @($User.SID.Value, "S-1-5-18", "S-1-5-32-544")
$AllowRules = @($Acl.Access | Where-Object {
    $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow
})
$ActualSids = @($AllowRules | ForEach-Object {
    $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
} | Select-Object -Unique)
foreach ($ExpectedSid in $ExpectedSids) {
    if ($ExpectedSid -notin $ActualSids) {
        Write-Error "FATAL: authorized key ACL is missing a required access rule"
        exit 1
    }
}
foreach ($ActualSid in $ActualSids) {
    if ($ActualSid -notin $ExpectedSids) {
        Write-Error "FATAL: authorized key ACL has an unexpected access rule"
        exit 1
    }
}
if (@($Acl.Access | Where-Object {
    $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny
}).Count -ne 0) {
    Write-Error "FATAL: authorized key ACL has an unexpected deny rule"
    exit 1
}
$Resolved = (& $Sshd -T -C "user=$Username,host=localhost,addr=127.0.0.1") -join "`n"
if ($LASTEXITCODE -ne 0) {
    Write-Error "FATAL: sshd effective configuration validation failed"
    exit 1
}
$ExpectedPath = "c:/users/$($Username.ToLower())/.ssh/authorized_keys"
if ($Resolved.ToLower() -notmatch ("authorizedkeysfile\s+" + [regex]::Escape($ExpectedPath))) {
    Write-Error "FATAL: sshd does not resolve the account-specific authorizedkeysfile"
    exit 1
}
Write-Output "Account-specific authorized key installed"
"""


class SetAuthorizedKeyPlan:
    """Install a public key for exactly one local account on Linux or Windows."""

    def __init__(self, *, platform: str) -> None:
        if platform not in ("linux", "windows"):
            raise ValueError(f"Unknown platform for SetAuthorizedKeyPlan: {platform!r}")
        self._platform = platform

    @property
    def steps(self) -> list[SetupStep]:
        script = LINUX_SET_AUTHORIZED_KEY_SCRIPT if self._platform == "linux" else WINDOWS_SET_AUTHORIZED_KEY_SCRIPT
        return [
            SetupStep(
                name=f"set_authorized_key_{self._platform}",
                script=script,
                timeout_seconds=120,
                requires_reboot=False,
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        script = (
            LINUX_VERIFY_AUTHORIZED_KEY_SCRIPT if self._platform == "linux" else WINDOWS_VERIFY_AUTHORIZED_KEY_SCRIPT
        )
        return SetupStep(
            name=f"verify_authorized_key_{self._platform}",
            script=script,
            timeout_seconds=60,
            is_verification=True,
        )

    def get_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Validate the authored username and generated public key context."""
        username = context.get("account_username")
        if not username:
            raise ValueError("SetAuthorizedKeyPlan requires non-empty account_username")
        if not context.get("account_public_key"):
            raise ValueError("SetAuthorizedKeyPlan requires non-empty account_public_key")
        quoted_username = (
            shlex.quote(str(username)) if self._platform == "linux" else "'" + str(username).replace("'", "''") + "'"
        )
        return {
            "account_username_quoted": quoted_username,
            "account_public_key": context["account_public_key"],
        }
