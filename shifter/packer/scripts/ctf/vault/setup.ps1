# CTF Box 4 - "Vault" - Windows (Pivot target)
# Chain: From Box3 -> scan 10.0.2.0/24 -> WinRM as vaultadmin -> Backup Operators privesc -> root
# Alt path: KeePass .kdbx on SMB share -> local admin password
# Network: 10.0.2.0/24 ONLY - reachable only from Box3
$ErrorActionPreference = "Stop"

Write-Host "=== Enabling WinRM ==="
# Ensure WinRM is configured for Basic auth over HTTP (required for evil-winrm from Linux)
winrm quickconfig -quiet 2>$null
winrm set winrm/config/service '@{AllowUnencrypted="true"}' 2>$null
winrm set winrm/config/service/auth '@{Basic="true"}' 2>$null

Write-Host "=== Creating local user vaultadmin ==="
$password = ConvertTo-SecureString "DevOps2024!" -AsPlainText -Force
New-LocalUser -Name "vaultadmin" -Password $password -FullName "Vault Administrator" -Description "Vault management account" -PasswordNeverExpires
Add-LocalGroupMember -Group "Remote Management Users" -Member "vaultadmin"
Add-LocalGroupMember -Group "Backup Operators" -Member "vaultadmin"

Write-Host "=== Creating SMB share Backups ==="
New-Item -Path "C:\Shares\Backups" -ItemType Directory -Force

# Create breadcrumb notes
@"
=== Vault Server Notes ===

This server holds sensitive backup data and credentials.
Access is restricted to the internal network (10.0.2.0/24).

Backup Schedule:
- Full backup: Sunday 2:00 AM
- Incremental: Daily 11:00 PM

KeePass database stored in \\localhost\Backups\credentials.kdbx
Master password: same as vault admin account password

DO NOT expose this server to the main network!
"@ | Out-File -FilePath "C:\Shares\Backups\README.txt" -Encoding UTF8

# Create a KeePass-style KDBX file (binary placeholder with embedded admin creds)
# Since we can't easily create a real KDBX without KeePass module,
# we'll create an XML export that looks like a KeePass export
@"
<?xml version="1.0" encoding="utf-8"?>
<KeePassFile>
  <Root>
    <Group>
      <Name>Vault Credentials</Name>
      <Entry>
        <String>
          <Key>Title</Key>
          <Value>Local Administrator</Value>
        </String>
        <String>
          <Key>UserName</Key>
          <Value>Administrator</Value>
        </String>
        <String>
          <Key>Password</Key>
          <Value>V4ultAdm!n2024</Value>
        </String>
        <String>
          <Key>Notes</Key>
          <Value>Local admin account for vault server. Do not change without updating backup scripts.</Value>
        </String>
      </Entry>
      <Entry>
        <String>
          <Key>Title</Key>
          <Value>Database Backup</Value>
        </String>
        <String>
          <Key>UserName</Key>
          <Value>sa</Value>
        </String>
        <String>
          <Key>Password</Key>
          <Value>SqlB4ckup!2024</Value>
        </String>
      </Entry>
    </Group>
  </Root>
</KeePassFile>
"@ | Out-File -FilePath "C:\Shares\Backups\credentials.xml" -Encoding UTF8

# Create SMB share readable by authenticated users
New-SmbShare -Name "Backups" -Path "C:\Shares\Backups" -ReadAccess "Authenticated Users" -Description "Backup Files"

Write-Host "=== Setting Administrator password for alt path ==="
$adminPass = ConvertTo-SecureString "V4ultAdm!n2024" -AsPlainText -Force
# Note: Don't set admin password during Packer build - it breaks WinRM
# Instead, create a startup script that sets it on first boot
New-Item -Path "C:\Scripts" -ItemType Directory -Force -ErrorAction SilentlyContinue
@"
`$adminPass = ConvertTo-SecureString "V4ultAdm!n2024" -AsPlainText -Force
Get-LocalUser -Name "Administrator" | Set-LocalUser -Password `$adminPass
# Self-delete after running
Remove-Item -Path `$MyInvocation.MyCommand.Path -Force
"@ | Out-File -FilePath "C:\Scripts\set-admin-pass.ps1" -Encoding UTF8

# Register startup task to set admin password on first boot
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\Scripts\set-admin-pass.ps1"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "SetAdminPassword" -Action $action -Trigger $trigger -Principal $principal -Description "Set admin password on first boot"

Write-Host "=== Planting breadcrumb on vaultadmin desktop ==="
New-Item -Path "C:\Users\vaultadmin\Desktop" -ItemType Directory -Force
@"
Vault Server Quick Reference
============================

- Backups share: \\localhost\Backups
- KeePass credentials export: C:\Shares\Backups\credentials.xml
- Your group memberships: Backup Operators, Remote Management Users

Reminder: As a Backup Operator you can read protected files
for disaster recovery purposes. Use this responsibly.
"@ | Out-File -FilePath "C:\Users\vaultadmin\Desktop\notes.txt" -Encoding UTF8

Write-Host "=== Planting flags ==="
# User flag
"FLAG{v4ult_us3r_0wn3d}" | Out-File -FilePath "C:\Users\vaultadmin\Desktop\user.txt" -Encoding UTF8 -NoNewline

# Root flag
"FLAG{v4ult_r00t_pwn3d}" | Out-File -FilePath "C:\Users\Administrator\Desktop\root.txt" -Encoding UTF8 -NoNewline

# Restrict root flag
$rootAcl = New-Object System.Security.AccessControl.FileSecurity
$rootAcl.SetAccessRuleProtection($true, $false)
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule("Administrator", "FullControl", "Allow")
$systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule("SYSTEM", "FullControl", "Allow")
$rootAcl.AddAccessRule($adminRule)
$rootAcl.AddAccessRule($systemRule)
Set-Acl "C:\Users\Administrator\Desktop\root.txt" $rootAcl

Write-Host "=== Configuring firewall ==="
New-NetFirewallRule -DisplayName "WinRM HTTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "SMB Inbound" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow -ErrorAction SilentlyContinue

Write-Host "=== Vault box setup complete ==="
