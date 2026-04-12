# CTF Box 4 - "Vault" - Windows
# Chain: Use Vault creds from Box3 -> WinRM as vaultadmin -> Backup Operators privesc -> root
# Alt path: KeePass .kdbx on SMB share -> local admin password
# Network: same workshop subnet as the other targets
$ErrorActionPreference = "Stop"

# WinRM already configured in base AMI (base.ps1 / user_data)

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
Access is restricted to the workshop range.

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

Write-Host "=== Preparing post-boot Administrator password override ==="
# Don't set the password during the Packer build; it breaks the active WinRM
# session. Instead, run a delayed startup script so it wins after the shared
# victim user_data applies the generic demo password on first boot.
New-Item -Path "C:\Scripts" -ItemType Directory -Force -ErrorAction SilentlyContinue
@"
Start-Sleep -Seconds 180
`$adminPass = ConvertTo-SecureString "V4ultAdm!n2024" -AsPlainText -Force
Get-LocalUser -Name "Administrator" | Set-LocalUser -Password `$adminPass
"@ | Out-File -FilePath "C:\Scripts\set-admin-pass.ps1" -Encoding UTF8

# Register delayed startup task to set admin password after user_data runs
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
"FLAG{vault_user_d1aadc0c3b961f4736d2}" | Out-File -FilePath "C:\Users\vaultadmin\Desktop\user.txt" -Encoding UTF8 -NoNewline

# Root flag
"FLAG{vault_root_c70f5667d45cabac71d4}" | Out-File -FilePath "C:\Users\Administrator\Desktop\root.txt" -Encoding UTF8 -NoNewline

# Restrict root flag
$rootAcl = New-Object System.Security.AccessControl.FileSecurity
$rootAcl.SetAccessRuleProtection($true, $false)
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule("Administrator", "FullControl", "Allow")
$systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule("SYSTEM", "FullControl", "Allow")
$rootAcl.AddAccessRule($adminRule)
$rootAcl.AddAccessRule($systemRule)
Set-Acl "C:\Users\Administrator\Desktop\root.txt" $rootAcl

Write-Host "=== Configuring firewall ==="
# WinRM firewall rule already in base AMI (base.ps1)
New-NetFirewallRule -DisplayName "SMB Inbound" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow -ErrorAction SilentlyContinue

Write-Host "=== Vault box setup complete ==="
