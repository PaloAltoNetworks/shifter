"""Read-only guest probes for bootstrap-realized RAES composition."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
from typing import Any

from raes_plan import RaesPlanAccount, RaesPlanContent

from .base import SetupStep

_SAFE_USERNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]{0,31}$")


def _fail_linux() -> str:
    """Return the fixed value-free Linux failure helper."""
    return "fail() { echo RAES_COMPOSITION_VERIFY_FAILED >&2; exit 1; }"


def _linux_content(item: RaesPlanContent) -> list[str]:
    """Render exact Linux probes for one bootstrap content item."""
    if item.content_type == "file" and item.text is not None and item.path:
        path = shlex.quote(item.path)
        digest = hashlib.sha256(item.text.encode()).hexdigest()
        mode = "600" if item.sensitive else "644"
        return [
            f"test -f {path} >/dev/null 2>&1 || fail",
            f"test ! -L {path} >/dev/null 2>&1 || fail",
            f"test \"$(sha256sum -- {path} 2>/dev/null | awk '{{print $1}}')\" = {digest} || fail",
            f"test \"$(stat -c '%u:%g:%a' -- {path} 2>/dev/null)\" = 0:0:{mode} || fail",
        ]
    target = item.destination or (item.path.rsplit("/", 1)[0] if item.path and "/" in item.path else "")
    if not target:
        return []
    quoted = shlex.quote(target)
    return [
        f"test -d {quoted} >/dev/null 2>&1 || fail",
        f"test ! -L {quoted} >/dev/null 2>&1 || fail",
    ]


def _linux_account(account: RaesPlanAccount) -> list[str]:
    """Render Linux identity and authentication-state probes for one account."""
    if not _SAFE_USERNAME.fullmatch(account.username):
        raise ValueError("invalid RAES account identity")
    user = shlex.quote(account.username)
    lines = [f"id {user} >/dev/null 2>&1 || fail"]
    for group in account.groups:
        quoted_group = shlex.quote(group)
        lines.append(f"id -nG {user} 2>/dev/null | tr ' ' '\\n' | grep -Fqx -- {quoted_group} || fail")
    if account.login_shell:
        lines.append(f'test "$(getent passwd {user} | cut -d: -f7)" = {shlex.quote(account.login_shell)} || fail')
    if account.home:
        home = shlex.quote(account.home)
        lines.extend(
            [
                f'test "$(getent passwd {user} | cut -d: -f6)" = {home} || fail',
                f"test -d {home} >/dev/null 2>&1 || fail",
                f"test ! -L {home} >/dev/null 2>&1 || fail",
            ]
        )
    if account.disabled:
        lines.append(f"passwd -S {user} 2>/dev/null | awk '{{print $2}}' | grep -Eq '^(L|LK)$' || fail")
    elif account.auth_method == "password":
        lines.append(f"passwd -S {user} 2>/dev/null | awk '{{print $2}}' | grep -Eq '^(P|PS)$' || fail")
    elif account.auth_method == "key":
        lines.extend(
            [
                f"account_home=$(getent passwd {user} | cut -d: -f6)",
                'test -s "$account_home/.ssh/authorized_keys" >/dev/null 2>&1 || fail',
                'test "$(stat -c \'%a\' -- "$account_home/.ssh" 2>/dev/null)" = 700 || fail',
                'test "$(stat -c \'%a\' -- "$account_home/.ssh/authorized_keys" 2>/dev/null)" = 600 || fail',
            ]
        )
    else:
        raise ValueError("unsupported RAES account authentication method")
    return lines


_WINDOWS_SCRIPT = r"""$ErrorActionPreference = 'Stop'
function Fail { Write-Error 'RAES_COMPOSITION_VERIFY_FAILED'; exit 1 }
function Assert-RaesPath {
    param([string]$Target)
    if ($Target.Length -lt 3) { Fail }
    $Drive = $Target.Substring(0, 1)
    $IsLetter = (($Drive -ge 'A') -and ($Drive -le 'Z')) -or (($Drive -ge 'a') -and ($Drive -le 'z'))
    if (-not $IsLetter -or $Target.Substring(1, 2) -ne ':\') { Fail }
    $Rest = $Target.Substring(3)
    if ($Rest.IndexOfAny([char[]]@('*', '?', '[', ']', ':')) -ge 0) { Fail }
    foreach ($Segment in $Rest.Split('\')) {
        if (($Segment -eq '..') -or ($Segment -eq '.')) { Fail }
    }
}
function Assert-SensitiveFileAcl {
    param([string]$Target)
    $Acl = Get-Acl -LiteralPath $Target
    if ($Acl.AreAccessRulesProtected -ne $true) { Fail }
    $ExpectedSids = @('S-1-5-18', 'S-1-5-32-544')
    if ($Acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-18') { Fail }
    $AllowRules = @($Acl.Access | Where-Object {
        $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow
    })
    $DenyRules = @($Acl.Access | Where-Object {
        $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny
    })
    if ($DenyRules.Count -ne 0 -or $AllowRules.Count -ne $ExpectedSids.Count) { Fail }
    $ActualSids = @($AllowRules | ForEach-Object {
        $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    })
    foreach ($Rule in $AllowRules) {
        if ($Rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { Fail }
    }
    foreach ($ExpectedSid in $ExpectedSids) {
        if ($ExpectedSid -notin $ActualSids) { Fail }
    }
    foreach ($ActualSid in $ActualSids) {
        if ($ActualSid -notin $ExpectedSids) { Fail }
    }
}
$PayloadLine = [Console]::In.ReadLine()
if ($null -eq $PayloadLine) { Fail }
try {
    $PayloadJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($PayloadLine))
    $Spec = $PayloadJson | ConvertFrom-Json
} catch { Fail }
$PayloadLine = $null
$PayloadJson = $null
foreach ($Content in @($Spec.content)) {
    $Target = [string]$Content.target
    Assert-RaesPath -Target $Target
    $Item = Get-Item -LiteralPath $Target -Force -ErrorAction Stop
    if ($Content.kind -eq 'file') {
        if ($Item.PSIsContainer -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Fail }
        if ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash -ne $Content.sha256) { Fail }
        if ($Content.sensitive -eq $true) { Assert-SensitiveFileAcl -Target $Target }
    } elseif ($Content.kind -eq 'directory') {
        if (-not $Item.PSIsContainer -or ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Fail }
    } else { Fail }
}
foreach ($Account in @($Spec.accounts)) {
    $Username = [string]$Account.username
    if ($Username -notmatch '^[A-Za-z_][A-Za-z0-9._-]{0,31}$') { Fail }
    $User = Get-LocalUser -Name $Username -ErrorAction Stop
    foreach ($Group in @($Account.groups)) {
        if (-not (Get-LocalGroupMember -Group $Group -ErrorAction Stop | Where-Object {
            $_.SID.Value -eq $User.SID.Value
        })) { Fail }
    }
    if ($User.Enabled -ne (-not [bool]$Account.disabled)) { Fail }
    if (-not $Account.disabled -and $Account.auth_method -eq 'key') {
        $KeyPath = "C:\Users\$Username\.ssh\authorized_keys"
        if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) { Fail }
        if ((Get-Item -LiteralPath $KeyPath).Length -le 0) { Fail }
        if ((Get-Acl -LiteralPath $KeyPath).AreAccessRulesProtected -ne $true) { Fail }
    } elseif (-not $Account.disabled -and $Account.auth_method -ne 'password') { Fail }
}
Write-Output 'RAES_COMPOSITION_VERIFIED'
"""


def _windows_stdin(content: tuple[RaesPlanContent, ...], accounts: tuple[RaesPlanAccount, ...]) -> str:
    """Serialize validated probe inputs onto the executor's separate stdin channel."""
    payload = {
        "content": [
            {
                "kind": item.content_type,
                "target": item.path if item.content_type == "file" else item.destination,
                "sha256": hashlib.sha256(item.text.encode()).hexdigest().upper() if item.text is not None else None,
                "sensitive": item.sensitive,
            }
            for item in content
        ],
        "accounts": [
            {
                "username": account.username,
                "groups": list(account.groups),
                "disabled": account.disabled,
                "auth_method": account.auth_method,
            }
            for account in accounts
        ],
    }
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")
    return encoded + "\n"


def _linux_script(content: tuple[RaesPlanContent, ...], accounts: tuple[RaesPlanAccount, ...]) -> str:
    """Render a fail-closed Linux composition verification script."""
    lines = ["#!/bin/bash", "set -euo pipefail", _fail_linux()]
    for item in content:
        lines.extend(_linux_content(item))
    for account in accounts:
        lines.extend(_linux_account(account))
    lines.append("echo RAES_COMPOSITION_VERIFIED")
    return "\n".join(lines) + "\n"


def _windows_script(content: tuple[RaesPlanContent, ...], accounts: tuple[RaesPlanAccount, ...]) -> str:
    """Return the fixed Windows verifier; its inputs travel over stdin."""
    del content, accounts
    return _WINDOWS_SCRIPT


class RaesCompositionVerificationPlan:
    """A verification-only setup plan for one node's bootstrap composition."""

    def __init__(
        self,
        *,
        platform: str,
        content: tuple[RaesPlanContent, ...],
        accounts: tuple[RaesPlanAccount, ...],
    ) -> None:
        if platform not in {"linux", "windows"}:
            raise ValueError("unsupported RAES composition verification platform")
        self._platform = platform
        self._content = content
        self._accounts = accounts

    @property
    def steps(self) -> list[SetupStep]:
        return []

    @property
    def verify_step(self) -> SetupStep:
        script = (
            _windows_script(self._content, self._accounts)
            if self._platform == "windows"
            else _linux_script(self._content, self._accounts)
        )
        return SetupStep(
            name=f"raes_verify_composition_{self._platform}",
            script=script,
            timeout_seconds=180,
            is_verification=True,
            stdin_input=_windows_stdin(self._content, self._accounts) if self._platform == "windows" else "",
        )

    @staticmethod
    def get_context(_instance: object) -> dict[str, Any]:
        """Return the empty setup context used by the verification-only plan."""
        return {}
