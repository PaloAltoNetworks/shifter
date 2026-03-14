# Validation script for CTF Box 2 - HelpDesk
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

Write-Host "=== Validating HelpDesk Box ==="

# Services
Check "IIS is running" { (Get-Service W3SVC).Status -eq "Running" }
Check "IIS index.html exists" { Test-Path "C:\inetpub\wwwroot\index.html" }
Check "IIS page contains HelpDesk" { (Get-Content "C:\inetpub\wwwroot\index.html" -Raw) -match "HelpDesk" }

# User
Check "helpdesk user exists" { Get-LocalUser -Name "helpdesk" -ErrorAction Stop; $true }
Check "helpdesk is in Administrators" { (Get-LocalGroupMember -Group "Administrators").Name -match "helpdesk" }
Check "helpdesk is in Remote Desktop Users" { (Get-LocalGroupMember -Group "Remote Desktop Users").Name -match "helpdesk" }

# SMB Share
Check "IT-Support share exists" { Get-SmbShare -Name "IT-Support" -ErrorAction Stop; $true }
Check "setup-notes.txt exists" { Test-Path "C:\Shares\IT-Support\setup-notes.txt" }
Check "deploy.ps1 exists" { Test-Path "C:\Shares\IT-Support\deploy.ps1" }
Check "setup-notes contains credentials" { (Get-Content "C:\Shares\IT-Support\setup-notes.txt" -Raw) -match "Summer2024!" }
Check "deploy.ps1 references SystemCleanup" { (Get-Content "C:\Shares\IT-Support\deploy.ps1" -Raw) -match "SystemCleanup" }

# Scheduled Task
Check "SystemCleanup task exists" { Get-ScheduledTask -TaskName "SystemCleanup" -ErrorAction Stop; $true }
Check "SystemCleanup runs as SYSTEM" { (Get-ScheduledTask -TaskName "SystemCleanup").Principal.UserId -eq "SYSTEM" }

# Cleanup script
Check "cleanup.ps1 exists" { Test-Path "C:\Scripts\cleanup.ps1" }
Check "helpdesk has write access to cleanup.ps1" {
    $acl = Get-Acl "C:\Scripts\cleanup.ps1"
    $acl.Access | Where-Object { $_.IdentityReference -match "helpdesk" -and $_.FileSystemRights -match "FullControl" }
}

# Flags
Check "User flag exists" { Test-Path "C:\Users\helpdesk\Desktop\user.txt" }
Check "Root flag exists" { Test-Path "C:\Users\Administrator\Desktop\root.txt" }
Check "User flag has correct content" { (Get-Content "C:\Users\helpdesk\Desktop\user.txt" -Raw) -match "FLAG" }
Check "Root flag has correct content" { (Get-Content "C:\Users\Administrator\Desktop\root.txt" -Raw) -match "FLAG" }

# Firewall
Check "SMB firewall rule exists" { Get-NetFirewallRule -DisplayName "SMB Inbound" -ErrorAction Stop; $true }
Check "RDP firewall rule exists" { Get-NetFirewallRule -DisplayName "RDP Inbound" -ErrorAction Stop; $true }

Write-Host ""
Write-Host "=== Results: $pass passed, $fail failed ==="
if ($fail -eq 0) { Write-Host "ALL CHECKS PASSED" } else { Write-Host "SOME CHECKS FAILED" }
exit $fail
