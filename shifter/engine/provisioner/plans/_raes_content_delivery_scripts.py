"""PowerShell script templates for Windows RAES source-backed content delivery.

Extracted from ``raes_content_delivery.py`` (Sonar S104). These are the
guest-side deliver/verify script bodies :class:`RaesContentDeliveryPlan`
injects as its setup steps on Windows targets; keeping the large embedded
PowerShell in its own module keeps the plan module under the Sonar line
budget. See that module's docstring for why the Windows dialect differs from
Linux (a genuine separate stdin channel, versus rendering every value directly
into the script text). The plan module imports these back, so its public
surface is unchanged.
"""

# ---------------------------------------------------------------------------
# Windows (PowerShell) -- every runtime value arrives over stdin, never
# templated into the ``-EncodedCommand`` argv. Verify steps use
# ``Read-RaesValue`` (one base64 line per ``[Console]::In.ReadLine()``, mirroring
# ``plans.raes_active_directory``); deliver steps use the raw-stream reader
# below because binary payload bytes follow their header lines.
# ---------------------------------------------------------------------------

_WINDOWS_READ_VALUE = r"""
function Read-RaesValue {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { exit 1 }
    try { return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line)) }
    catch { exit 1 }
}
"""

# A canonical local drive-letter absolute path only (``C:\...``). Plain string
# operations, deliberately not regex -- easy to audit by inspection, no
# escaping ambiguity across the Python-raw-string -> PowerShell-single-quoted
# -> regex-engine layers a hand-rolled pattern would otherwise cross.
#
# Rejects, all fail-closed:
# - UNC paths (``\\server\share\...``) and device-namespace paths
#   (``\\.\...``, ``\\?\...``) -- neither starts with a drive letter, so the
#   very first check already excludes them. A UNC target reaching a privileged
#   file-write API makes the guest attempt outbound SMB authentication as the
#   execution identity -- a credential-capture / relay risk, not just a
#   filesystem one.
# - a second ``:`` anywhere after the drive letter (alternate data streams).
# - wildcard-aware characters (``*``, ``?``, ``[``, ``]``) that a later
#   ``-Path`` (as opposed to ``-LiteralPath``) call could expand against
#   unintended files -- most importantly the directory dialect's recursive
#   ``Remove-Item`` before reconciliation.
# - any ``.``/``..`` path segment (defense in depth against a normalized
#   escape even though the path is already required to be absolute).
_WINDOWS_VALIDATE_TARGET = r"""
function Assert-RaesTargetPath {
    param([string]$Target)
    if ($Target.Length -lt 3) { throw "unsafe target path" }
    $Drive = $Target.Substring(0, 1)
    $IsLetter = (($Drive -ge 'A') -and ($Drive -le 'Z')) -or (($Drive -ge 'a') -and ($Drive -le 'z'))
    if (-not $IsLetter) { throw "unsafe target path" }
    if ($Target.Substring(1, 2) -ne ':\') { throw "unsafe target path" }
    $Rest = $Target.Substring(3)
    if ($Rest.IndexOfAny([char[]]@('*', '?', '[', ']', ':')) -ge 0) { throw "unsafe target path" }
    foreach ($Segment in $Rest.Split('\')) {
        if (($Segment -eq '..') -or ($Segment -eq '.')) { throw "unsafe target path" }
    }
}
"""

# Deliver steps read stdin only through the raw standard-input stream: four
# base64 header lines (read byte-wise, so nothing is buffered past them), then
# the raw payload copied from the same stream. Mixing in ``[Console]::In`` would
# let its read-ahead swallow payload bytes.
_WINDOWS_STREAM_INPUT = r"""
$RaesIn = [Console]::OpenStandardInput()
function Read-RaesHeaderValue {
    $Buffer = New-Object System.Collections.Generic.List[byte]
    while ($true) {
        $Next = $RaesIn.ReadByte()
        if ($Next -lt 0) { exit 1 }
        if ($Next -eq 10) { break }
        if ($Next -ne 13) { $Buffer.Add([byte]$Next) }
        if ($Buffer.Count -gt 8192) { exit 1 }
    }
    try {
        $Text = [Text.Encoding]::ASCII.GetString($Buffer.ToArray())
        return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Text))
    }
    catch { exit 1 }
}
function Assert-RaesFreeSpace {
    param([string]$Path, [long]$Required)
    $Drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Path))
    if ($Drive.AvailableFreeSpace -lt $Required) { throw "insufficient free space" }
}
function Receive-RaesPayload {
    param([string]$Path, [long]$ExpectedBytes, [string]$ExpectedSha256)
    $Out = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $RaesIn.CopyTo($Out) } finally { $Out.Dispose() }
    if ((Get-Item -LiteralPath $Path).Length -ne $ExpectedBytes) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        Write-Error "RAES_CONTENT_DELIVERY_SIZE_MISMATCH"
        exit 1
    }
    $ActualSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedSha256) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        Write-Error "RAES_CONTENT_DELIVERY_DIGEST_MISMATCH"
        exit 1
    }
}
"""

WINDOWS_DELIVER_FILE_SCRIPT = (
    _WINDOWS_STREAM_INPUT
    + _WINDOWS_VALIDATE_TARGET
    + r"""
$ErrorActionPreference = "Stop"
$TargetPath = Read-RaesHeaderValue
$ExpectedSha256 = Read-RaesHeaderValue
$Sensitive = Read-RaesHeaderValue
$ExpectedBytes = [long](Read-RaesHeaderValue)
try {
    if (-not $TargetPath -or -not $ExpectedSha256) { exit 1 }
    Assert-RaesTargetPath -Target $TargetPath
    $ParentDir = Split-Path -Parent $TargetPath
    New-Item -ItemType Directory -Force -Path $ParentDir | Out-Null
    Assert-RaesFreeSpace -Path $ParentDir -Required $ExpectedBytes
    $Staging = Join-Path $ParentDir ("." + [Guid]::NewGuid().ToString("N") + ".raes-content.tmp")
    Receive-RaesPayload -Path $Staging -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256
    Move-Item -LiteralPath $Staging -Destination $TargetPath -Force
    if ($Sensitive -eq "1") {
        # Least-permissive: SYSTEM + Administrators only (mirrors chmod 600 intent).
        $Acl = Get-Acl -LiteralPath $TargetPath
        $Acl.SetAccessRuleProtection($true, $false)
        $SystemSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-18")
        $AdministratorsSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
        foreach ($Identity in @($SystemSid, $AdministratorsSid)) {
            $Acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
                $Identity,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                [System.Security.AccessControl.AccessControlType]::Allow
            ))
        }
        Set-Acl -LiteralPath $TargetPath -AclObject $Acl
    }
    Write-Output "RAES_CONTENT_FILE_INSTALLED"
    exit 0
} catch { Write-Error "RAES_CONTENT_DELIVERY_FAILED"; exit 1 }
"""
)

WINDOWS_VERIFY_FILE_SCRIPT = (
    _WINDOWS_READ_VALUE
    + _WINDOWS_VALIDATE_TARGET
    + r"""
$ErrorActionPreference = "Stop"
$TargetPath = Read-RaesValue
$ExpectedSha256 = Read-RaesValue
try {
    Assert-RaesTargetPath -Target $TargetPath
    $Item = Get-Item -LiteralPath $TargetPath -ErrorAction Stop
    if ($Item.LinkType) {
        Write-Error "RAES_CONTENT_DELIVERY_READBACK_FAILED"
        exit 1
    }
    $ActualSha256 = (Get-FileHash -LiteralPath $TargetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedSha256) {
        Write-Error "RAES_CONTENT_DELIVERY_READBACK_FAILED"
        exit 1
    }
    Write-Output "RAES_CONTENT_FILE_VERIFIED"
    exit 0
} catch { Write-Error "RAES_CONTENT_DELIVERY_READBACK_FAILED"; exit 1 }
"""
)

WINDOWS_DELIVER_DIRECTORY_SCRIPT = (
    _WINDOWS_STREAM_INPUT
    + _WINDOWS_VALIDATE_TARGET
    + r"""
$ErrorActionPreference = "Stop"
$Destination = Read-RaesHeaderValue
$ExpectedSha256 = Read-RaesHeaderValue
$Sensitive = Read-RaesHeaderValue
$ExpectedBytes = [long](Read-RaesHeaderValue)
try {
    if (-not $Destination -or -not $ExpectedSha256) { exit 1 }
    $Destination = $Destination.TrimEnd('\')
    Assert-RaesTargetPath -Target $Destination
    $ParentDir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $ParentDir | Out-Null
    # The staged archive and its extraction coexist until publish.
    Assert-RaesFreeSpace -Path $ParentDir -Required (2 * $ExpectedBytes)
    # An exclusively-named, unpredictable staging path (guid, like the file
    # dialect) -- never a fixed sibling name -- removed by this same step right
    # after extraction; verify_step proves the installed tree, so it never
    # needs to relocate this (or any) retained archive.
    $StagingTar = Join-Path $ParentDir ("." + [Guid]::NewGuid().ToString("N") + ".raes-content-staging.tar")
    Receive-RaesPayload -Path $StagingTar -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256
    $Listing = & tar.exe -tvf $StagingTar
    if ($LASTEXITCODE -ne 0) { throw "archive listing failed" }
    foreach ($Line in $Listing) {
        if ($Line.Length -gt 0 -and $Line[0] -eq 'l') { throw "archive contains a symlink entry" }
    }
    $Names = & tar.exe -tf $StagingTar
    if ($LASTEXITCODE -ne 0) { throw "archive listing failed" }
    foreach ($Name in $Names) {
        if ($Name.StartsWith("/") -or $Name -match '(^|[/\\])\.\.([/\\]|$)') { throw "archive contains an unsafe path" }
    }
    $ExtractDir = Join-Path $ParentDir ([Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
    & tar.exe -xf $StagingTar -C $ExtractDir
    if ($LASTEXITCODE -ne 0) { throw "archive extraction failed" }
    Remove-Item -LiteralPath $StagingTar -Force -ErrorAction SilentlyContinue
    if ($Sensitive -eq "1") {
        # Least-permissive: SYSTEM + Administrators only, applied to the
        # private extraction tree *before* it is published atomically -- the
        # extraction directory otherwise inherits its (author-controlled)
        # parent's ACL, which is commonly Users-readable.
        $DirAcl = Get-Acl -LiteralPath $ExtractDir
        $DirAcl.SetAccessRuleProtection($true, $false)
        $SystemSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-18")
        $AdministratorsSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
        $Inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        foreach ($Identity in @($SystemSid, $AdministratorsSid)) {
            $DirAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
                $Identity,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $Inherit,
                [System.Security.AccessControl.PropagationFlags]::None,
                [System.Security.AccessControl.AccessControlType]::Allow
            ))
        }
        Set-Acl -LiteralPath $ExtractDir -AclObject $DirAcl
    }
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    Move-Item -LiteralPath $ExtractDir -Destination $Destination -Force
    Write-Output "RAES_CONTENT_DIRECTORY_INSTALLED"
    exit 0
} catch { Write-Error "RAES_CONTENT_DELIVERY_FAILED"; exit 1 }
"""
)

WINDOWS_VERIFY_DIRECTORY_SCRIPT = (
    _WINDOWS_READ_VALUE
    + _WINDOWS_VALIDATE_TARGET
    + r"""
$ErrorActionPreference = "Stop"
$Destination = (Read-RaesValue).TrimEnd('\')
$ExpectedTreeSha256 = Read-RaesValue
try {
    Assert-RaesTargetPath -Target $Destination
    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) { throw "destination missing" }
    $DestItem = Get-Item -LiteralPath $Destination -Force
    if ($DestItem.LinkType) { throw "destination is a reparse point" }
    # Deterministic installed-tree manifest -- mirrors the Linux verify script
    # and raes_content_payload.installed_tree_sha256 exactly: every regular
    # file under $Destination (reparse points excluded), ordinal-sorted by its
    # forward-slash-normalized relative path, one "<sha256>  <relpath>`n" line
    # each.
    $RelToHash = @{}
    Get-ChildItem -LiteralPath $Destination -Recurse -Force -File | Where-Object { -not $_.LinkType } | ForEach-Object {
        $Rel = $_.FullName.Substring($Destination.Length).TrimStart('\').Replace('\', '/')
        $RelToHash[$Rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $SortedRel = [string[]]$RelToHash.Keys
    [Array]::Sort($SortedRel, [StringComparer]::Ordinal)
    $Manifest = New-Object System.Text.StringBuilder
    foreach ($Rel in $SortedRel) {
        [void]$Manifest.Append($RelToHash[$Rel]).Append("  ").Append($Rel).Append("`n")
    }
    $ManifestBytes = [Text.Encoding]::UTF8.GetBytes($Manifest.ToString())
    $ManifestHash = [Security.Cryptography.SHA256]::Create().ComputeHash($ManifestBytes)
    $ActualTreeSha256 = [BitConverter]::ToString($ManifestHash).Replace('-', '').ToLowerInvariant()
    if ($ActualTreeSha256 -ne $ExpectedTreeSha256) { throw "digest mismatch" }
    Write-Output "RAES_CONTENT_DIRECTORY_VERIFIED"
    exit 0
} catch { Write-Error "RAES_CONTENT_DELIVERY_READBACK_FAILED"; exit 1 }
"""
)
