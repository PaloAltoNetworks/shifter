# CTF Box 2 - "HelpDesk" - Windows
# Chain: SMB open share -> creds in setup-notes.txt -> RDP as helpdesk ->
#        scheduled task runs cleanup.ps1 as SYSTEM -> modify script -> root flag
$ErrorActionPreference = "Stop"

# IIS and W3SVC already installed and configured in base AMI (services.ps1)

# Create static helpdesk page
$iisRoot = "C:\inetpub\wwwroot"
@"
<!DOCTYPE html>
<html>
<head><title>IT HelpDesk Portal</title></head>
<body>
<h1>IT HelpDesk Portal</h1>
<p>Welcome to the IT HelpDesk self-service portal.</p>
<p>For support, email <a href="mailto:helpdesk@corp.local">helpdesk@corp.local</a></p>
<h2>Quick Links</h2>
<ul>
  <li><a href="#">Password Reset</a></li>
  <li><a href="#">VPN Setup Guide</a></li>
  <li><a href="#">New Hire Checklist</a></li>
</ul>
<footer><small>IT Department - Internal Use Only</small></footer>
</body>
</html>
"@ | Out-File -FilePath "$iisRoot\index.html" -Encoding UTF8 -Force

Write-Host "=== Creating local user helpdesk ==="
$password = ConvertTo-SecureString "Summer2024!" -AsPlainText -Force
New-LocalUser -Name "helpdesk" -Password $password -FullName "HelpDesk Admin" -Description "IT HelpDesk temporary admin account" -PasswordNeverExpires
Add-LocalGroupMember -Group "Administrators" -Member "helpdesk"
Add-LocalGroupMember -Group "Remote Desktop Users" -Member "helpdesk"

Write-Host "=== Creating SMB share IT-Support ==="
New-Item -Path "C:\Shares\IT-Support" -ItemType Directory -Force

# setup-notes.txt with leaked credentials
@"
=== IT Support Setup Notes ===
Date: 2024-06-15
Author: sysadmin

Deployment Notes:
- HelpDesk portal deployed to IIS on this server
- Temp admin account created for initial setup
  Username: helpdesk
  Password: Summer2024!
  TODO: Change this password before go-live!

- Cleanup script configured to run every 2 minutes
  Path: C:\Scripts\cleanup.ps1
  Runs as: SYSTEM (via scheduled task)

- Next steps:
  1. Configure SSL certificate
  2. Set up monitoring
  3. Remove temp admin account
"@ | Out-File -FilePath "C:\Shares\IT-Support\setup-notes.txt" -Encoding UTF8

# deploy.ps1 referencing the scheduled task
@"
# HelpDesk Deployment Script
# Run this after initial server setup

# Verify IIS is running
Get-Service W3SVC

# Check scheduled task is active
Get-ScheduledTask -TaskName "SystemCleanup" | Select-Object TaskName, State

# Verify cleanup script exists
if (Test-Path "C:\Scripts\cleanup.ps1") {
    Write-Host "Cleanup script found"
} else {
    Write-Host "WARNING: Cleanup script missing!"
}

Write-Host "Deployment check complete."
"@ | Out-File -FilePath "C:\Shares\IT-Support\deploy.ps1" -Encoding UTF8

# Enable Guest account for anonymous SMB access
net user Guest /active:yes
net user Guest ""

# Grant Guest read on the NTFS folder
icacls "C:\Shares\IT-Support" /grant "Guest:(OI)(CI)R" /T

# Create the SMB share - readable by Everyone and Guest
New-SmbShare -Name "IT-Support" -Path "C:\Shares\IT-Support" -ReadAccess "Everyone","Guest" -Description "IT Support Documentation"

# Allow null/guest sessions to access the share
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters" -Name "RestrictNullSessAccess" -Value 0 -Type DWord -Force

Write-Host "=== Creating scheduled task ==="
New-Item -Path "C:\Scripts" -ItemType Directory -Force

# cleanup.ps1 - the script that runs as SYSTEM
@"
# System Cleanup Script
# Cleans temporary files and logs
`$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path "C:\Scripts\cleanup.log" -Value "`$timestamp - Cleanup ran"
Remove-Item -Path "C:\Windows\Temp\*.tmp" -Force -ErrorAction SilentlyContinue
"@ | Out-File -FilePath "C:\Scripts\cleanup.ps1" -Encoding UTF8

# Grant helpdesk user write access to the script
$acl = Get-Acl "C:\Scripts\cleanup.ps1"
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("helpdesk", "FullControl", "Allow")
$acl.SetAccessRule($rule)
Set-Acl "C:\Scripts\cleanup.ps1" $acl

# Create scheduled task running as SYSTEM every 2 minutes
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\Scripts\cleanup.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "SystemCleanup" -Action $action -Trigger $trigger -Principal $principal -Description "Automated system cleanup"

Write-Host "=== Planting flags ==="
# User flag
New-Item -Path "C:\Users\helpdesk\Desktop" -ItemType Directory -Force
"FLAG{h3lpd3sk_us3r_0wn3d}" | Out-File -FilePath "C:\Users\helpdesk\Desktop\user.txt" -Encoding UTF8 -NoNewline

# Root flag
"FLAG{h3lpd3sk_r00t_pwn3d}" | Out-File -FilePath "C:\Users\Administrator\Desktop\root.txt" -Encoding UTF8 -NoNewline

# Restrict root flag to Administrator only
$rootAcl = New-Object System.Security.AccessControl.FileSecurity
$rootAcl.SetAccessRuleProtection($true, $false)
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule("Administrator", "FullControl", "Allow")
$systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule("SYSTEM", "FullControl", "Allow")
$rootAcl.AddAccessRule($adminRule)
$rootAcl.AddAccessRule($systemRule)
Set-Acl "C:\Users\Administrator\Desktop\root.txt" $rootAcl

Write-Host "=== Configuring firewall ==="
# RDP and HTTP firewall rules already in base AMI (base.ps1)
New-NetFirewallRule -DisplayName "SMB Inbound" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow -ErrorAction SilentlyContinue

Write-Host "=== HelpDesk box setup complete ==="
