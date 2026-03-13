# Validation script for CTF Box 4 - Vault
$ErrorActionPreference = "Continue"
$pass = 0
$fail = 0

function Check {
    param([string]$Description, [scriptblock]$Test)
    try {
        $result = & $Test
        if ($result) {
            Write-Host "[PASS] $Description"
            $script:pass++
        } else {
            Write-Host "[FAIL] $Description"
            $script:fail++
        }
    } catch {
        Write-Host "[FAIL] $Description - Error: $_"
        $script:fail++
    }
}

Write-Host "=== Validating Vault Box ==="

# WinRM
Check "WinRM service is running" { (Get-Service WinRM).Status -eq "Running" }

# User
Check "vaultadmin user exists" { Get-LocalUser -Name "vaultadmin" -ErrorAction Stop; $true }
Check "vaultadmin is in Backup Operators" { (Get-LocalGroupMember -Group "Backup Operators").Name -match "vaultadmin" }
Check "vaultadmin is in Remote Management Users" { (Get-LocalGroupMember -Group "Remote Management Users").Name -match "vaultadmin" }

# SMB Share
Check "Backups share exists" { Get-SmbShare -Name "Backups" -ErrorAction Stop; $true }
Check "README.txt exists in share" { Test-Path "C:\Shares\Backups\README.txt" }
Check "credentials.xml exists in share" { Test-Path "C:\Shares\Backups\credentials.xml" }
Check "README mentions KeePass" { (Get-Content "C:\Shares\Backups\README.txt" -Raw) -match "KeePass" }
Check "credentials.xml contains admin password" { (Get-Content "C:\Shares\Backups\credentials.xml" -Raw) -match "V4ultAdm!n2024" }

# Breadcrumbs
Check "vaultadmin desktop notes exist" { Test-Path "C:\Users\vaultadmin\Desktop\notes.txt" }
Check "Notes mention Backup Operators" { (Get-Content "C:\Users\vaultadmin\Desktop\notes.txt" -Raw) -match "Backup Operator" }

# Admin password startup script
Check "Admin password script exists" { Test-Path "C:\Scripts\set-admin-pass.ps1" }
Check "SetAdminPassword task exists" { Get-ScheduledTask -TaskName "SetAdminPassword" -ErrorAction Stop; $true }

# Flags
Check "User flag exists" { Test-Path "C:\Users\vaultadmin\Desktop\user.txt" }
Check "Root flag exists" { Test-Path "C:\Users\Administrator\Desktop\root.txt" }
Check "User flag has correct content" { (Get-Content "C:\Users\vaultadmin\Desktop\user.txt" -Raw) -match "FLAG" }
Check "Root flag has correct content" { (Get-Content "C:\Users\Administrator\Desktop\root.txt" -Raw) -match "FLAG" }

# Root flag permissions
Check "Root flag restricted to admin" {
    $acl = Get-Acl "C:\Users\Administrator\Desktop\root.txt"
    $nonAdmin = $acl.Access | Where-Object { $_.IdentityReference -notmatch "Administrator|SYSTEM" }
    -not $nonAdmin
}

# Firewall
Check "WinRM firewall rule exists" { Get-NetFirewallRule -DisplayName "WinRM HTTP Inbound" -ErrorAction Stop; $true }
Check "SMB firewall rule exists" { Get-NetFirewallRule -DisplayName "SMB Inbound" -ErrorAction Stop; $true }

Write-Host ""
Write-Host "=== Results: $pass passed, $fail failed ==="
if ($fail -eq 0) { Write-Host "ALL CHECKS PASSED" } else { Write-Host "SOME CHECKS FAILED" }
exit $fail
