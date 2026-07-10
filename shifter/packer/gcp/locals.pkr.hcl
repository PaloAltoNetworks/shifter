// Shared build-time bootstrap for the Windows GCE builders (windows + dc).
//
// Single source of truth for the WinRM-over-TLS bootstrap so both Windows
// templates harden identically (#505 codex security review): an HTTPS WinRM
// listener on 5986 bound to a self-signed cert, Basic-over-HTTP disabled, and
// only 5986 opened on the firewall. The transient local admin (packer_user)
// and this listener live on the ephemeral builder VM only; GCESysprep removes
// them before the image is captured, so the bootstrap password never persists
// into the published image and never crosses the wire in cleartext.
locals {
  winrm_https_bootstrap_ps1 = <<-EOT
    $ErrorActionPreference = 'Stop'
    $pw = ConvertTo-SecureString '${var.winrm_bootstrap_password}' -AsPlainText -Force
    New-LocalUser -Name 'packer_user' -Password $pw -PasswordNeverExpires -AccountNeverExpires
    Add-LocalGroupMember -Group 'Administrators' -Member 'packer_user'

    winrm quickconfig -quiet
    # Disable plaintext transport and HTTP Basic; require an encrypted channel.
    winrm set winrm/config/service '@{AllowUnencrypted="false"}'
    winrm set winrm/config/service/auth '@{Basic="false"}'

    # Self-signed cert for the ephemeral builder; bind an HTTPS listener on 5986
    # and remove any plaintext HTTP listener that quickconfig created.
    $cert = New-SelfSignedCertificate -DnsName ([System.Net.Dns]::GetHostName()) -CertStoreLocation Cert:\LocalMachine\My
    $thumb = $cert.Thumbprint
    Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTPS"} -ErrorAction SilentlyContinue
    New-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTPS"} -ValueSet @{Hostname=([System.Net.Dns]::GetHostName());CertificateThumbprint=$thumb}
    Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTP"} -ErrorAction SilentlyContinue

    netsh advfirewall firewall add rule name="WinRM-HTTPS-5986" protocol=TCP dir=in localport=5986 action=allow
    netsh advfirewall firewall delete rule name="WinRM-5985" protocol=TCP localport=5985
  EOT

  # Variant for the polaris-dc (BOREAS.LOCAL) GDC image bake. Uses the built-in
  # Administrator so the identity survives the AD promotion reboot as the domain
  # Administrator; the polaris-dc builder disables the GCE account manager so it
  # does not reset the password out from under packer's WinRM connection. This
  # image is captured un-sysprepped on purpose (a promoted DC cannot be
  # generalized), so the bootstrap identity is retained by design.
  winrm_https_bootstrap_dc_ps1 = <<-EOT
    $ErrorActionPreference = 'Stop'
    # Use the built-in Administrator (net user is bulletproof vs Set-LocalUser on
    # a possibly-disabled account) so the identity survives the promotion reboot
    # as the domain Administrator.
    net user Administrator '${var.winrm_bootstrap_password}' /active:yes

    winrm quickconfig -quiet
    winrm set winrm/config/service '@{AllowUnencrypted="false"}'
    winrm set winrm/config/service/auth '@{Basic="false"}'

    $cert = New-SelfSignedCertificate -DnsName ([System.Net.Dns]::GetHostName()) -CertStoreLocation Cert:\LocalMachine\My
    $thumb = $cert.Thumbprint
    Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTPS"} -ErrorAction SilentlyContinue
    New-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTPS"} -ValueSet @{Hostname=([System.Net.Dns]::GetHostName());CertificateThumbprint=$thumb}
    Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTP"} -ErrorAction SilentlyContinue

    netsh advfirewall firewall add rule name="WinRM-HTTPS-5986" protocol=TCP dir=in localport=5986 action=allow
    netsh advfirewall firewall delete rule name="WinRM-5985" protocol=TCP localport=5985
  EOT
}
