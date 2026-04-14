<powershell>
# POLARIS A2 Windows Server 2022 first-boot bootstrap (minimal).
#
# Deliberately small: just the things that MUST happen before SSM comes up.
# Everything else (AD DS install, promotion, OU/user/group/share setup) runs
# via SSM Run Command after the agent reports online, so failures are
# observable and re-runnable from the operator side.
#
# Side note: the prior attempt against the shifter-dc-prebaked AMI raced
# EC2Launch v2 sysprep against SSM agent start and the agent came up with
# "RequestError: send request failed" at IMDSv2. Stock Windows Server 2022
# Full Base + a minimal user_data avoids that path entirely.

$ErrorActionPreference = "Continue"
$LogFile = "C:\polaris-bootstrap.log"
Start-Transcript -Path $LogFile -Append

Write-Host "=== POLARIS A2 first-boot $(Get-Date -Format o) ==="

try {
    # Set Administrator password to the operator-known value so the
    # post-promotion scripts (and the Shifter portal RDP chain) can log in.
    $AdminPassword = "${admin_password}"
    net user Administrator $AdminPassword 2>&1 | Out-Null
    Write-Host "  Administrator password set"

    # Disable Windows Firewall on every profile. The polaris security group
    # is the only boundary we care about and the CTF attack tooling (impacket,
    # ldapsearch, smbclient, pth) needs clean packet paths.
    Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
    Write-Host "  Windows Firewall disabled on all profiles"

    # Enable RDP so Guacamole-style connections from the portal work.
    Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name "fDenyTSConnections" -Value 0
    Set-Service -Name TermService -StartupType Automatic
    Start-Service -Name TermService -ErrorAction SilentlyContinue
    Write-Host "  RDP enabled"

    # Ensure SSM agent + EC2Launch agent are set to auto-start. They already
    # are on the Microsoft-provided AMI but we re-assert in case a future
    # base image flips defaults.
    Set-Service -Name AmazonSSMAgent -StartupType Automatic -ErrorAction SilentlyContinue
    Start-Service -Name AmazonSSMAgent -ErrorAction SilentlyContinue
    Write-Host "  AmazonSSMAgent started"
} catch {
    Write-Host "bootstrap error: $_"
}

Stop-Transcript
</powershell>
<persist>false</persist>
