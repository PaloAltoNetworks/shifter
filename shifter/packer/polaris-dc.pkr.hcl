// polaris-dc: a PRE-PROMOTED Windows Server 2022 domain controller AMI for the
// Polaris (NORTHSTORM) scenario. Promotion runs at bake time so a range boots an
// already-promoted BOREAS.LOCAL DC instead of paying ~15-20 min of per-range
// promotion. This is the amazon-ebs twin of shifter/packer/gcp/dc-prebaked.pkr.hcl
// and reuses the same cloud-neutral scripts (base.ps1, services.ps1, a2_setup.ps1,
// promote-bake.ps1); the only AWS-specific finalize is dc-content-seed.ps1 (no
// GDC UEFI-fallback staging).
//
// The domain, NetBIOS name and AD-content seed are variables so one template can
// bake other-domain DCs; the defaults reproduce the Polaris BOREAS.LOCAL image.
//
// Captured UN-SYSPREPPED on purpose: sysprep cannot generalize a promoted domain
// controller. WinRM uses NTLM so the connection survives the promotion reboot —
// the built-in Administrator becomes the domain Administrator (same password).
source "amazon-ebs" "polaris-dc" {
  ami_name        = "${var.ami_prefix}-polaris-dc-{{timestamp}}"
  ami_description = "Polaris pre-promoted ${var.dc_domain_name} DC (17 OUs/users, SPNs, DCSync ACL, shares, OpenSSH) - un-sysprepped"
  instance_type   = var.instance_type
  region          = var.aws_region

  source_ami_filter {
    filters = {
      name                = "Windows_Server-2022-English-Full-Base-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"]
  }

  // WinRM over NTLM so the reconnect after the promotion reboot authenticates as
  // the domain Administrator (Basic auth is refused once the box is a DC).
  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_use_ssl  = false
  winrm_insecure = true
  winrm_use_ntlm = true
  winrm_timeout  = "40m"

  user_data = <<-EOF
    <powershell>
    Set-ExecutionPolicy Unrestricted -Force
    winrm quickconfig -quiet
    winrm set winrm/config/service '@{AllowUnencrypted="true"}'
    winrm set winrm/config/service/auth '@{Basic="true"}'
    winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'
    netsh advfirewall firewall add rule name="WinRM HTTP" dir=in action=allow protocol=TCP localport=5985
    Restart-Service WinRM
    </powershell>
  EOF

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true
  pause_before_connecting     = "1m"

  tags = {
    Name      = "${var.ami_prefix}-polaris-dc"
    Project   = "shifter"
    Scenario  = "polaris"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-polaris-dc"
  }
}

build {
  sources = ["source.amazon-ebs.polaris-dc"]

  // Base system configuration (RDP, firewall, AD DS feature) for the dc role.
  provisioner "powershell" {
    environment_vars = ["PACKER_ROLE=dc"]
    script           = "scripts/windows/base.ps1"
  }

  // Services incl. OpenSSH Server (the range provisioner's dc_setup step requires
  // OpenSSH preinstalled on the polaris-dc AMI). elevated_user is required for
  // Add-WindowsCapability over WinRM.
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = build.Password
    environment_vars  = ["PACKER_ROLE=dc"]
    script            = "scripts/windows/services.ps1"
  }

  // Stage the AD content seed for dc-content-seed.ps1 to run post-promotion.
  provisioner "powershell" {
    inline = ["New-Item -ItemType Directory -Force -Path C:\\polaris | Out-Null"]
  }
  provisioner "file" {
    source      = var.dc_content_script
    destination = "C:\\polaris\\a2_setup.ps1"
  }

  // Install AD DS/DNS and Install-ADDSForest for the domain, deferring the reboot
  // to the windows-restart below (cloud-neutral; shared with the GCE dc-prebaked).
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = build.Password
    environment_vars = [
      "DC_DOMAIN_NAME=${var.dc_domain_name}",
      "DC_NETBIOS_NAME=${var.dc_netbios_name}",
    ]
    script = "gcp/scripts/dc-prebaked/promote-bake.ps1"
  }

  provisioner "windows-restart" {
    restart_timeout = "20m"
  }

  // Post-reboot (reconnected as the domain Administrator): wait for AD DS, then
  // run the AD content seed. MUST BE LAST - the seed sets the CTF Administrator
  // password.
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = build.Password
    script            = "scripts/windows/dc-content-seed.ps1"
  }

  post-processor "manifest" {
    output     = "polaris-dc-manifest.json"
    strip_path = true
  }
}
